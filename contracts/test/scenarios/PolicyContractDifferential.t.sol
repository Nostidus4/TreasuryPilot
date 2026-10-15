// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {TreasuryFixture} from "../helpers/TreasuryFixture.sol";
import {ITreasuryPilotModule as I} from "../../src/interfaces/ITreasuryPilotModule.sol";

/// @notice Contract half of POL-004. Expected outcomes come from the same JSON matrix as pytest.
contract PolicyContractDifferentialTest is TreasuryFixture {
    string internal constant CASES = "test/vectors/policy_contract_differential.json";

    function test_differential_validPay() external {
        _comparePay("valid_pay", _approval(100, 1500e6));
    }

    function test_differential_perRequestCapExact() external {
        _comparePay("cap_exact", _approval(101, 2000e6));
    }

    function test_differential_perRequestCapPlusOne() external {
        _comparePay("cap_plus_one", _approval(102, 2000e6 + 1));
    }

    function test_differential_dailyLimit() external {
        I.PaymentApproval memory ap;
        for (uint256 i; i < 5; ++i) {
            ap = _approval(200 + i, 1998e6);
            _pay(ap, bytes32(200 + i));
        }
        _comparePay("daily_limit", _approval(206, 11e6));
    }

    function test_differential_unknownPayee() external {
        I.PaymentApproval memory ap = _approval(103, 1e6);
        ap.payee = address(0xABCD);
        _comparePay("unknown_payee", ap);
    }

    function test_differential_coolingBeforeEdge() external {
        address newPayee = address(0xBEE1);
        _owner(abi.encodeCall(module.addPayee, (newPayee)));
        I.PaymentApproval memory ap = _approval(104, 1e6);
        ap.payee = newPayee;
        _comparePay("cooling_before_edge", ap);
    }

    function test_differential_coolingAtEdge() external {
        address newPayee = address(0xBEE2);
        _owner(abi.encodeCall(module.addPayee, (newPayee)));
        (, uint64 activeFrom) = module.payeeStatus(newPayee);
        vm.warp(activeFrom);
        I.PaymentApproval memory ap = _approval(105, 1e6);
        ap.payee = newPayee;
        _comparePay("cooling_at_edge", ap);
    }

    function test_differential_pausedMandate() external {
        _owner(abi.encodeCall(module.pause, ()));
        _comparePay("mandate_paused", _approval(106, 1e6));
    }

    function test_differential_expiredApproval() external {
        I.PaymentApproval memory ap = _approval(107, 1e6);
        ap.expiry = uint64(block.timestamp - 1);
        _comparePay("approval_expired", ap);
    }

    function test_differential_refillBound() external {
        I.PaymentApproval memory ap = _approval(108, 100e6);
        _compareRefill("refill_bound", ap, 1e6);
    }

    function test_differential_validException() external {
        I.PaymentApproval memory ap = _approval(109, 2500e6);
        _owner(
            abi.encodeCall(
                module.grantException, (ap.requestId, uint128(ap.amount), ap.payee, uint64(block.timestamp + 1 days))
            )
        );
        _comparePay("valid_exception", ap);
    }

    function test_differential_invalidException() external {
        I.PaymentApproval memory ap = _approval(110, 2500e6);
        _owner(
            abi.encodeCall(
                module.grantException,
                (ap.requestId, uint128(ap.amount - 1), ap.payee, uint64(block.timestamp + 1 days))
            )
        );
        _comparePay("invalid_exception", ap);
    }

    function test_differential_duplicateBlocked() external {
        I.PaymentApproval memory first = _approval(111, 1e6);
        _pay(first, bytes32(uint256(111)));
        I.PaymentApproval memory duplicate = _approval(112, 1e6);
        duplicate.fingerprint = first.fingerprint;
        _comparePay("duplicate_blocked", duplicate);
    }

    function test_differential_duplicateAllowed() external {
        I.PaymentApproval memory first = _approval(113, 1e6);
        _pay(first, bytes32(uint256(113)));
        I.PaymentApproval memory duplicate = _approval(114, 1e6);
        duplicate.fingerprint = first.fingerprint;
        _owner(abi.encodeCall(module.allowDuplicate, (duplicate.fingerprint, duplicate.requestId)));
        _comparePay("duplicate_allowed", duplicate);
    }

    function test_differential_revokedMandate() external {
        _owner(abi.encodeCall(module.revoke, ()));
        _comparePay("mandate_revoked", _approval(115, 1e6));
    }

    function test_differential_expiredMandate() external {
        vm.warp(config.expiresAt + 1);
        _comparePay("mandate_expired", _approval(116, 1e6));
    }

    function test_differential_notStartedMandate() external {
        vm.warp(config.validFrom - 1);
        _comparePay("mandate_not_started", _approval(117, 1e6));
    }

    function test_differential_revokedAndExpiredMandate() external {
        _owner(abi.encodeCall(module.revoke, ()));
        vm.warp(config.expiresAt + 1);
        _comparePay("mandate_revoked_and_expired", _approval(118, 1e6));
    }

    function test_differential_pausedAndExpiredMandate() external {
        _owner(abi.encodeCall(module.pause, ()));
        vm.warp(config.expiresAt + 1);
        _comparePay("mandate_paused_and_expired", _approval(119, 1e6));
    }

    // --- AT-05 variants ---

    function test_differential_approvalPayeeChanged() external {
        I.PaymentApproval memory signed = _approval(120, 1e6);
        I.PaymentApproval memory ap = _approval(120, 1e6);
        ap.payee = address(0x99);
        _compareCall(
            "approval_payee_changed",
            abi.encodeCall(module.pay, (ap, _sign(signed), keccak256("approval_payee_changed"), ap.amount)),
            executor
        );
    }

    function test_differential_approvalMissing() external {
        I.PaymentApproval memory ap = _approval(121, 1e6);
        _compareCall(
            "approval_missing",
            abi.encodeCall(module.pay, (ap, bytes(""), keccak256("approval_missing"), ap.amount)),
            executor
        );
    }

    function test_differential_approvalBadSignature() external {
        I.PaymentApproval memory ap = _approval(122, 1e6);
        _compareCall(
            "approval_bad_signature",
            abi.encodeCall(
                module.pay, (ap, _sign(_approval(123, 1e6 + 1)), keccak256("approval_bad_signature"), ap.amount)
            ),
            executor
        );
    }

    function test_differential_approvalSignerNotApprover() external {
        I.PaymentApproval memory ap = _approval(124, 1e6);
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(8, module.hashApproval(ap));
        bytes memory sig = abi.encode(vm.addr(8), abi.encodePacked(r, s, v));
        _compareCall(
            "approval_signer_not_approver",
            abi.encodeCall(module.pay, (ap, sig, keccak256("approval_signer_not_approver"), ap.amount)),
            executor
        );
    }

    // --- buffers ---

    function test_differential_bufferBreach() external {
        _setBalance(address(op1), 1505e6);
        _comparePay("buffer_breach", _approval(125, 1500e6));
    }

    function test_differential_sourceBufferBreach() external {
        _setBalance(address(op1), 50e6);
        _setBalance(address(treasury), 1000e6 + 500_000);
        _compareRefill("source_buffer_breach", _approval(126, 100e6), 1e6);
    }

    // --- boundaries ---

    function test_differential_dailyCapExact() external {
        token.mint(address(op1), 10000e6);
        for (uint256 i; i < 5; ++i) {
            _pay(_approval(210 + i, 1800e6), bytes32(210 + i));
        }
        _comparePay("daily_exact", _approval(216, 1000e6));
    }

    function test_differential_refillBoundExact() external {
        _setBalance(address(op1), 200e6);
        _compareRefill("refill_bound_exact", _approval(127, 100e6), 50e6);
    }

    function test_differential_overRefillPerRequest() external {
        _setBalance(address(op1), 0);
        _compareRefill("refill_per_request", _approval(128, 3000e6), 2500e6 + 1);
    }

    function test_differential_overRefillDaily() external {
        for (uint256 i; i < 5; ++i) {
            _setBalance(address(op1), 0);
            _refill(_approval(300 + i, 3000e6), bytes32(300 + i), 2400e6);
        }
        _setBalance(address(op1), 50e6);
        _compareRefill("refill_daily", _approval(306, 100e6), 1e6);
    }

    // --- replay, option and caller ---

    function test_differential_wrongPaymentOption() external {
        I.PaymentApproval memory ap = _approval(129, 1500e6);
        _compareCall(
            "wrong_payment_option",
            abi.encodeCall(module.pay, (ap, _sign(ap), keccak256("wrong_payment_option"), ap.amount - 1)),
            executor
        );
    }

    function test_differential_requestAlreadyPaid() external {
        I.PaymentApproval memory ap = _approval(130, 1e6);
        _pay(ap, bytes32(uint256(130)));
        _comparePay("request_already_paid", ap);
    }

    function test_differential_requestCancelled() external {
        I.PaymentApproval memory ap = _approval(131, 1e6);
        _owner(abi.encodeCall(module.cancelRequest, (ap.requestId)));
        _comparePay("request_cancelled", ap);
    }

    function test_differential_stepAlreadyExecuted() external {
        _pay(_approval(132, 1e6), keccak256("step_already_executed"));
        _comparePay("step_already_executed", _approval(133, 1e6));
    }

    function test_differential_alreadyRefilledForRequest() external {
        _setBalance(address(op1), 50e6);
        I.PaymentApproval memory ap = _approval(134, 100e6);
        _refill(ap, bytes32(uint256(134)), 1e6);
        _compareRefill("refill_already_done", ap, 1e6);
    }

    function test_differential_notExecutor() external {
        I.PaymentApproval memory ap = _approval(135, 1e6);
        _compareCall(
            "not_executor",
            abi.encodeCall(module.pay, (ap, _sign(ap), keccak256("not_executor"), ap.amount)),
            address(0xBAD)
        );
    }

    /// @dev Moves the surplus out of a wallet with a pranked token transfer.
    function _setBalance(address wallet, uint256 target) internal {
        uint256 surplus = token.balanceOf(wallet) - target;
        vm.prank(wallet);
        token.transfer(address(0xDEAD), surplus);
    }

    function _compareCall(string memory caseId, bytes memory callData, address caller) internal {
        _compare(caseId, callData, caller);
    }

    function _comparePay(string memory caseId, I.PaymentApproval memory ap) internal {
        _compare(caseId, abi.encodeCall(module.pay, (ap, _sign(ap), keccak256(bytes(caseId)), ap.amount)));
    }

    function _compareRefill(string memory caseId, I.PaymentApproval memory ap, uint256 amount) internal {
        _compare(
            caseId, abi.encodeCall(module.refill, (ap, _sign(ap), keccak256(bytes(caseId)), ap.payingWallet, amount))
        );
    }

    function _compare(string memory caseId, bytes memory callData) internal {
        _compare(caseId, callData, executor);
    }

    function _compare(string memory caseId, bytes memory callData, address caller) internal {
        string memory json = vm.readFile(CASES);
        string memory root = string.concat(".", caseId);
        bool expectedSuccess = vm.parseJsonBool(json, string.concat(root, ".contract_success"));
        vm.prank(caller);
        (bool success, bytes memory result) = address(module).call(callData);
        require(success == expectedSuccess, string.concat(caseId, ": success mismatch"));
        if (!expectedSuccess) {
            string memory signature = vm.parseJsonString(json, string.concat(root, ".contract_error"));
            bytes4 expected = bytes4(keccak256(bytes(signature)));
            bytes4 actual;
            if (result.length >= 4) {
                assembly {
                    actual := mload(add(result, 32))
                }
            }
            require(actual == expected, string.concat(caseId, ": revert selector mismatch"));
        }
    }
}
