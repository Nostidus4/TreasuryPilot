"""Scenario steps (DEV-007): each drives the deployed module on Anvil and asserts its own must-show.

Every step sends real transactions with the Anvil demo identities (executor, owner Safe signer,
guardian) and a payment approval signed by the demo approver key, then checks the result on chain
(balances, module state, expected custom-error reverts). The Aave steps use the TEST-only
MockAavePool that `Deploy.s.sol` deploys on Anvil.
shortcut: this plays the contract and policy layers directly; the planner, sequencer, AI
extraction, outbox and chain-reader services are stood in for by the assertions below, not run.
Upgrade when a service-account API client can drive those services end to end.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from eth_abi import encode
from eth_account import Account
from eth_utils import keccak
from seed_local import ANVIL, rpc

from treasurypilot_core.domain.fee_policy import (
    FeeDecision,
    assess_fee,
    estimate_plan_fee_wei,
    propose_fee_policy,
)

OWNER, EXECUTOR, GUARDIAN, PAYEE, OUTSIDER = ANVIL[0], ANVIL[1], ANVIL[3], ANVIL[4], ANVIL[6]
APPROVER_KEY = "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a"  # Anvil #2
APPROVAL_TYPE = (
    "(bytes32,bytes32,bytes32,address,address,address,address,uint256,uint256,uint64,uint64,"
    "bytes32,uint64,bool)"
)
USDC = 10**6
TRANSFER_TOPIC = "0x" + keccak(text="Transfer(address,address,uint256)").hex()


class ScenarioError(Exception):
    """A failed precondition or must-show assertion."""


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise ScenarioError(message)


class Chain:
    """Thin JSON-RPC wrapper bound to one run: records every receipt for the evidence bundle."""

    def __init__(self, ctx: dict[str, Any]) -> None:
        self.ctx, self.url = ctx, ctx["rpc_url"]
        manifest = ctx["manifest"]
        self.module, self.treasury = manifest["module"], manifest["safeT"]
        self.op1, self.token = manifest["safeO1"], manifest["asset"]
        self.pool, self.atoken = manifest["aavePool"], manifest["aToken"]

    def call(self, to: str, signature: str, types: list[str], args: list[Any]) -> bytes:
        return bytes.fromhex(
            rpc(self.url, "eth_call", [self._tx(None, to, signature, types, args), "latest"])[2:]
        )

    def uint(self, to: str, signature: str, types: list[str], args: list[Any]) -> int:
        return int.from_bytes(self.call(to, signature, types, args)[-32:], "big")

    def balance(self, wallet: str) -> int:
        return self.uint(self.token, "balanceOf(address)", ["address"], [wallet])

    def _tx(
        self, sender: str | None, to: str, signature: str, types: list[str], args: list[Any]
    ) -> dict[str, str]:
        data = "0x" + (keccak(text=signature)[:4] + encode(types, args)).hex()
        return (
            {"to": to, "data": data} if sender is None else {"from": sender, "to": to, "data": data}
        )

    def send(
        self, sender: str, to: str, signature: str, types: list[str], args: list[Any]
    ) -> dict[str, Any]:
        tx = rpc(self.url, "eth_sendTransaction", [self._tx(sender, to, signature, types, args)])
        for _ in range(50):  # Anvil may mine a moment after the send returns
            if (receipt := rpc(self.url, "eth_getTransactionReceipt", [tx])) is not None:
                break
            time.sleep(0.2)
        _check(
            receipt is not None and receipt["status"] == "0x1", f"{signature} transaction failed"
        )
        self.ctx["transactions"].append(receipt)
        return receipt  # type: ignore[no-any-return]

    def reverts_with(
        self, error: str, sender: str, to: str, signature: str, types: list[str], args: list[Any]
    ) -> None:
        """Assert the call reverts with custom error `error()`; nothing is mined."""
        selector = keccak(text=f"{error}()")[:4].hex()
        try:
            rpc(self.url, "eth_call", [self._tx(sender, to, signature, types, args), "latest"])
        except RuntimeError as exc:
            _check(selector in str(exc).lower(), f"expected {error}, got {exc}")
            return
        raise ScenarioError(f"expected {error}, but the call succeeded")

    def now(self) -> int:
        return int(rpc(self.url, "eth_getBlockByNumber", ["latest", False])["timestamp"], 16)

    def warp(self, seconds: int) -> None:
        rpc(self.url, "evm_increaseTime", [seconds])
        rpc(self.url, "evm_mine", [])

    def safe_exec(
        self, safe: str, to: str, signature: str, types: list[str], args: list[Any]
    ) -> dict[str, Any]:
        """Owner-approved Safe transaction (1-of-1, approved-hash signature)."""
        data = keccak(text=signature)[:4] + encode(types, args)
        owner_sig = bytes(12) + bytes.fromhex(OWNER[2:]) + bytes(32) + b"\x01"
        return self.send(
            OWNER, safe,
            "execTransaction(address,uint256,bytes,uint8,uint256,uint256,uint256,address,address,bytes)",
            ["address", "uint256", "bytes", "uint8", "uint256", "uint256", "uint256", "address", "address", "bytes"],
            [to, 0, data, 0, 0, 0, 0, "0x" + "00" * 20, "0x" + "00" * 20, owner_sig],
        )  # fmt: skip

    def owner(self, signature: str, types: list[str], args: list[Any]) -> dict[str, Any]:
        return self.safe_exec(self.treasury, self.module, signature, types, args)

    def approval(self, name: str, n: int, amount: int, payee: str = PAYEE) -> tuple[Any, ...]:
        seed = f"{self.ctx['run_id']}:{name}:{n}"
        deadline = self.now() + 86_400
        return (
            keccak(text=f"request:{seed}"), keccak(text=f"invoice:{seed}"), keccak(text=f"fp:{seed}"),
            self.module, self.op1, self.token, payee, amount, 0, 0, deadline, keccak(text="terms"),
            deadline, False,
        )  # fmt: skip

    def sig(self, approval: tuple[Any, ...]) -> bytes:
        digest = self.call(
            self.module, f"hashApproval({APPROVAL_TYPE})", [APPROVAL_TYPE], [approval]
        )
        signed = Account.unsafe_sign_hash(digest, APPROVER_KEY).signature
        return encode(["address", "bytes"], [Account.from_key(APPROVER_KEY).address, signed])

    def _approved(
        self,
        method: str,
        approval: tuple[Any, ...],
        step: str,
        extra: list[Any],
        extra_types: list[str],
    ) -> tuple[str, list[str], list[Any]]:
        stepid = keccak(text=f"{self.ctx['run_id']}:{step}")
        return (
            f"{method}({APPROVAL_TYPE},bytes,bytes32{''.join(',' + t for t in extra_types)})",
            [APPROVAL_TYPE, "bytes", "bytes32", *extra_types],
            [approval, self.sig(approval), stepid, *extra],
        )

    def pay_args(self, approval: tuple[Any, ...], step: str) -> tuple[str, list[str], list[Any]]:
        return self._approved("pay", approval, step, [approval[7]], ["uint256"])

    def refill_args(
        self, approval: tuple[Any, ...], step: str, amount: int
    ) -> tuple[str, list[str], list[Any]]:
        return self._approved(
            "refill", approval, step, [approval[4], amount], ["address", "uint256"]
        )

    def refill(self, approval: tuple[Any, ...], step: str, amount: int) -> dict[str, Any]:
        signature, types, args = self.refill_args(approval, step, amount)
        return self.send(EXECUTOR, self.module, signature, types, args)

    def pay(self, approval: tuple[Any, ...], step: str) -> dict[str, Any]:
        signature, types, args = self.pay_args(approval, step)
        return self.send(EXECUTOR, self.module, signature, types, args)

    def request_paid(self, approval: tuple[Any, ...]) -> bool:
        return bool(self.uint(self.module, "requestPaid(bytes32)", ["bytes32"], [approval[0]]))

    def status(self) -> int:
        return self.uint(self.module, "status()", [], [])

    def cooled(self) -> None:
        """Move past the payee cooling period so the demo payee is Active."""
        self.warp(301)

    def refill_amount(self, amount: int) -> int:
        """Refill that lifts Safe O1 to payment + its 10 tUSDC floor."""
        return max(amount + 10 * USDC - self.balance(self.op1), 1)


def _paid(amount: int, c: Chain, approval: tuple[Any, ...], before: int) -> None:
    _check(c.request_paid(approval), "request not marked paid on chain")
    _check(c.balance(PAYEE) - before == amount, "payee did not receive exactly the approved amount")


def refill_then_pay(ctx: dict[str, Any]) -> dict[str, Any]:
    c, amount = Chain(ctx), 800 * USDC
    c.cooled()
    ap, before = c.approval("demo", 1, amount), c.balance(PAYEE)
    top_up = c.refill_amount(amount)
    refill_tx = c.refill(ap, "refill", top_up)["transactionHash"]
    pay_tx = c.pay(ap, "pay")["transactionHash"]
    _paid(amount, c, ap, before)
    s, t, a = c.pay_args(ap, "pay-again")
    c.reverts_with("RequestAlreadyPaid", EXECUTOR, c.module, s, t, a)
    return {
        "step": "refill_then_pay",
        "refillTx": refill_tx,
        "payTx": pay_tx,
        "paid": amount,
        "replayRejected": True,
    }


def over_cap_exception(ctx: dict[str, Any]) -> dict[str, Any]:
    c, amount = Chain(ctx), 2500 * USDC  # per-request pay cap is 2000 tUSDC
    c.cooled()
    ap, before = c.approval("over-cap", 1, amount), c.balance(PAYEE)
    c.refill(ap, "refill", c.refill_amount(amount))
    s, t, a = c.pay_args(ap, "pay-blocked")
    c.reverts_with("OverPerRequestLimit", EXECUTOR, c.module, s, t, a)
    _check(not c.request_paid(ap), "over-cap payment went through without an exception")
    grant = c.owner(
        "grantException(bytes32,uint128,address,uint64)",
        ["bytes32", "uint128", "address", "uint64"], [ap[0], amount, PAYEE, c.now() + 3600],
    )  # fmt: skip
    pay_tx = c.pay(ap, "pay-excepted")["transactionHash"]
    _paid(amount, c, ap, before)
    s, t, a = c.pay_args(ap, "pay-again")
    c.reverts_with("RequestAlreadyPaid", EXECUTOR, c.module, s, t, a)
    return {
        "step": "over_cap_exception",
        "blockedBy": "OverPerRequestLimit",
        "exceptionTx": grant["transactionHash"],
        "payTx": pay_tx,
    }


def unknown_payee_blocked(ctx: dict[str, Any]) -> dict[str, Any]:
    c, amount = Chain(ctx), 800 * USDC
    ap = c.approval("injected", 1, amount, payee=OUTSIDER)  # a payee injected by the invoice text
    before = c.balance(OUTSIDER)
    s, t, a = c.pay_args(ap, "pay-unknown")
    c.reverts_with("PayeeUnknown", EXECUTOR, c.module, s, t, a)
    _check(
        c.balance(OUTSIDER) == before and not c.request_paid(ap), "funds moved to an unknown payee"
    )
    return {"step": "unknown_payee_blocked", "blockedBy": "PayeeUnknown", "paid": 0}


def crash_after_refill(ctx: dict[str, Any]) -> dict[str, Any]:
    c, amount = Chain(ctx), 800 * USDC
    c.cooled()
    ap, before = c.approval("crash", 1, amount), c.balance(PAYEE)
    top_up = c.refill_amount(amount)
    c.refill(ap, "refill", top_up)  # the worker dies here, before sending PAY
    # Recovery rebuilds from chain state alone: the refill is on chain, the payment is not.
    _check(
        bool(
            c.uint(c.module, "refilledFor(bytes32,address)", ["bytes32", "address"], [ap[0], c.op1])
        )
        and not c.request_paid(ap),
        "chain state does not show a half-finished request",
    )
    s, t, a = c.refill_args(ap, "refill-retry", top_up)  # a blind retry of the refill is refused
    c.reverts_with("AlreadyRefilledForRequest", EXECUTOR, c.module, s, t, a)
    pay_tx = c.pay(ap, "pay")["transactionHash"]
    _paid(amount, c, ap, before)
    s, t, a = c.pay_args(ap, "pay-retry")
    c.reverts_with("RequestAlreadyPaid", EXECUTOR, c.module, s, t, a)
    return {
        "step": "crash_after_refill",
        "payTx": pay_tx,
        "paid": amount,
        "doublePayRejected": True,
    }


def guardian_pause(ctx: dict[str, Any]) -> dict[str, Any]:
    c = Chain(ctx)
    if ctx["chain_id"] != 31337:  # the guardian sender is an unlocked Anvil account
        raise ScenarioError(
            "guardian_pause needs a local Anvil (chain 31337) with unlocked accounts"
        )
    if rpc(c.url, "eth_getCode", [c.module, "latest"]) in ("0x", ""):
        raise ScenarioError(f"module {c.module} has no code; run `make deploy-local`")
    if c.status() != 0:
        raise ScenarioError("module is not Active (already paused?); run `make deploy-local`")
    receipt = c.send(GUARDIAN, c.module, "pause()", [], [])
    status = c.status()
    if status != 1:
        raise ScenarioError(f"module status is {status} after pause, expected 1 (Paused)")
    return {
        "step": "guardian_pause",
        "txHash": receipt["transactionHash"],
        "moduleStatus": "Paused",
    }


def supply_surplus(ctx: dict[str, Any]) -> dict[str, Any]:
    c, floor = Chain(ctx), 1000 * USDC  # Safe T buffer
    surplus = c.balance(c.treasury) - floor
    _check(surplus > 0, "Safe T has no surplus above its reserve")
    amount = min(surplus, 5000 * USDC)  # supply per-request cap
    receipt = c.send(
        EXECUTOR,
        c.module,
        "supply(bytes32,uint256)",
        ["bytes32", "uint256"],
        [keccak(text=f"{ctx['run_id']}:supply"), amount],
    )
    _check(c.balance(c.treasury) >= floor, "supply broke the Safe T reserve")
    _check(
        c.uint(c.atoken, "balanceOf(address)", ["address"], [c.treasury]) == amount,
        "aToken balance != supplied amount",
    )
    return {
        "step": "supply_surplus",
        "txHash": receipt["transactionHash"],
        "supplied": amount,
        "reserveKept": floor,
    }


def withdraw_for_invoice(ctx: dict[str, Any]) -> dict[str, Any]:
    c, amount = Chain(ctx), 800 * USDC
    c.cooled()
    # Idle cash is parked in Aave except the reserve, then a new invoice needs it back.
    parked = c.balance(c.treasury) - 1000 * USDC
    c.send(
        EXECUTOR,
        c.module,
        "supply(bytes32,uint256)",
        ["bytes32", "uint256"],
        [keccak(text=f"{ctx['run_id']}:park"), min(parked, 5000 * USDC)],
    )
    ap, before = c.approval("withdraw", 1, amount), c.balance(PAYEE)
    cash = c.balance(c.treasury)
    receipt = c.send(
        EXECUTOR,
        c.module,
        "withdraw(bytes32,uint256)",
        ["bytes32", "uint256"],
        [keccak(text=f"{ctx['run_id']}:withdraw"), amount],
    )
    _check(c.balance(c.treasury) - cash == amount, "withdraw did not restore the cash into Safe T")
    c.refill(ap, "refill", c.refill_amount(amount))
    c.pay(ap, "pay")
    _paid(amount, c, ap, before)
    return {
        "step": "withdraw_for_invoice",
        "withdrawTx": receipt["transactionHash"],
        "withdrawn": amount,
    }


def _plan(ctx: dict[str, Any], label: str) -> bytes:
    return keccak(text=f"{ctx['run_id']}:{label}")


def borrow_unauthorized(ctx: dict[str, Any]) -> dict[str, Any]:
    c = Chain(ctx)
    plan = _plan(ctx, "borrow-proposal")
    c.reverts_with(
        "BorrowNotAuthorized", EXECUTOR, c.module, "borrow(bytes32)", ["bytes32"], [plan]
    )
    _check(
        c.uint(c.pool, "debt(address)", ["address"], [c.treasury]) == 0,
        "debt exists without an authorization",
    )
    return {"step": "borrow_unauthorized", "blockedBy": "BorrowNotAuthorized", "debt": 0}


def _authorize_and_borrow(
    c: Chain, ctx: dict[str, Any], label: str, amount: int
) -> tuple[bytes, dict[str, Any], dict[str, Any]]:
    plan = _plan(ctx, label)
    cash = c.balance(c.treasury)
    auth = c.owner(
        "authorizeBorrow(bytes32,uint256,uint64,uint256,uint256)",
        ["bytes32", "uint256", "uint64", "uint256", "uint256"], [plan, amount, c.now() + 3600, 15 * 10**17, 10**26],
    )  # fmt: skip
    borrow = c.send(EXECUTOR, c.module, "borrow(bytes32)", ["bytes32"], [plan])
    _check(
        c.balance(c.treasury) - cash == amount,
        "borrow did not deliver exactly the authorized amount",
    )
    _check(
        c.uint(c.pool, "debt(address)", ["address"], [c.treasury]) == amount,
        "pool debt != authorized amount",
    )
    c.reverts_with(
        "BorrowNotAuthorized", EXECUTOR, c.module, "borrow(bytes32)", ["bytes32"], [plan]
    )  # one-time
    return plan, auth, borrow


def owner_borrow(ctx: dict[str, Any]) -> dict[str, Any]:
    c, amount = Chain(ctx), 500 * USDC
    _, auth, borrow = _authorize_and_borrow(c, ctx, "borrow-execution", amount)
    return {
        "step": "owner_borrow",
        "authorizeTx": auth["transactionHash"],
        "borrowTx": borrow["transactionHash"],
        "borrowed": amount,
        "reuseRejected": True,
    }


def owner_borrow_repay(ctx: dict[str, Any]) -> dict[str, Any]:
    c, amount = Chain(ctx), 500 * USDC
    _authorize_and_borrow(c, ctx, "borrow-repay", amount)
    plan = _plan(ctx, "repay")
    c.owner(
        "authorizeRepay(bytes32,uint256,uint64)",
        ["bytes32", "uint256", "uint64"],
        [plan, amount, c.now() + 3600],
    )
    repay = c.send(EXECUTOR, c.module, "repay(bytes32)", ["bytes32"], [plan])
    _check(
        c.uint(c.pool, "debt(address)", ["address"], [c.treasury]) == 0,
        "debt not closed by the repayment",
    )
    return {
        "step": "owner_borrow_repay",
        "repayTx": repay["transactionHash"],
        "repaid": amount,
        "debt": 0,
    }


def outflow_alert(ctx: dict[str, Any]) -> dict[str, Any]:
    """A Safe O1 token transfer that bypasses the module is flagged; the module's own pay is not."""
    c, amount = Chain(ctx), 800 * USDC
    c.cooled()
    first_block = hex(int(rpc(c.url, "eth_blockNumber", []), 16) + 1)
    ap = c.approval("outflow", 1, amount)
    c.refill(ap, "refill", c.refill_amount(amount))
    c.pay(ap, "pay")
    stray = c.safe_exec(
        c.op1, c.token, "transfer(address,uint256)", ["address", "uint256"], [OUTSIDER, 5 * USDC]
    )
    logs = rpc(c.url, "eth_getLogs", [{"address": c.token, "fromBlock": first_block, "toBlock": "latest",
                                       "topics": [TRANSFER_TOPIC, "0x" + bytes(12).hex() + c.op1[2:].lower()]}])  # fmt: skip
    alerts = [
        log["transactionHash"] for log in logs
        if rpc(c.url, "eth_getTransactionReceipt", [log["transactionHash"]])["to"].lower() != c.module.lower()
    ]  # fmt: skip
    _check(
        alerts == [stray["transactionHash"]],
        f"expected exactly the stray transfer flagged, got {alerts}",
    )
    return {
        "step": "outflow_alert",
        "alert": "UNEXPECTED_OUTFLOW",
        "flaggedTx": alerts[0],
        "blocksPendingPay": True,
    }


def fee_spike_defers(ctx: dict[str, Any]) -> dict[str, Any]:
    c, amount = Chain(ctx), 800 * USDC
    c.cooled()
    ap, before = c.approval("fee-spike", 1, amount), c.balance(PAYEE)
    refill = c.refill(ap, "refill", c.refill_amount(amount))
    normal_fee = int(refill["gasUsed"], 16) * int(refill["effectiveGasPrice"], 16)
    base = int(rpc(c.url, "eth_getBlockByNumber", ["latest", False])["baseFeePerGas"], 16)
    policy = propose_fee_policy(
        plan_fees_wei=[normal_fee],
        plans_last_7d=1,
        base_fee_per_gas_wei=base,
        priority_fees_wei=[10**9],
    )
    pay_gas = int(
        rpc(c.url, "eth_estimateGas", [c._tx(EXECUTOR, c.module, *c.pay_args(ap, "pay"))]), 16
    )

    def assess(base_fee: int) -> Any:
        fee = estimate_plan_fee_wei(
            [pay_gas], [base_fee * policy.max_fee_multiplier_bps // 10_000 + 10**9]
        )
        return assess_fee(
            estimated_fee_wei=fee, per_plan_threshold_wei=policy.per_plan_threshold_wei, spent_today_wei=normal_fee,
            daily_budget_wei=policy.daily_budget_wei, last_safe_execution_at=datetime.now(UTC) + timedelta(hours=1),
        )  # fmt: skip

    def set_base_fee(value: int) -> int:
        rpc(c.url, "anvil_setNextBlockBaseFeePerGas", [hex(value)])
        rpc(c.url, "evm_mine", [])
        return int(rpc(c.url, "eth_getBlockByNumber", ["latest", False])["baseFeePerGas"], 16)

    _check(assess(base).decision is FeeDecision.PROCEED, "a normal base fee should proceed")
    spiked = set_base_fee(base * 100)
    held = assess(spiked)
    _check(
        held.decision is FeeDecision.DEFER and held.reason_code == "FEE_ABOVE_THRESHOLD",
        f"spike not held: {held}",
    )
    _check(not c.request_paid(ap), "payment was sent during the fee spike")
    calm = set_base_fee(base)
    _check(assess(calm).decision is FeeDecision.PROCEED, "fee did not clear after the spike")
    pay_tx = c.pay(ap, "pay")["transactionHash"]
    _paid(amount, c, ap, before)
    return {"step": "fee_spike_defers", "decision": held.decision.value, "reason": held.reason_code,
            "spikeBaseFeeWei": spiked, "payTx": pay_tx}  # fmt: skip


# step name -> (function, capabilities it provides); AVAILABLE is derived from this.
LOCAL = frozenset({"anvil", "deployment"})
STEPS: dict[str, tuple[Callable[[dict[str, Any]], dict[str, Any]], frozenset[str]]] = {
    fn.__name__: (fn, LOCAL | extra)
    for fn, extra in (
        (guardian_pause, frozenset()), (refill_then_pay, frozenset()), (over_cap_exception, frozenset()),
        (unknown_payee_blocked, frozenset()), (crash_after_refill, frozenset()), (outflow_alert, frozenset()),
        (fee_spike_defers, frozenset()), (supply_surplus, frozenset({"aave-mock"})),
        (withdraw_for_invoice, frozenset({"aave-mock"})), (borrow_unauthorized, frozenset({"aave-mock"})),
        (owner_borrow, frozenset({"aave-mock"})), (owner_borrow_repay, frozenset({"aave-mock"})),
    )
}  # fmt: skip
