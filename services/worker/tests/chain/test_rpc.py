from __future__ import annotations

import asyncio
from typing import Any

import pytest
from eth_abi import encode

from treasurypilot_worker.chain import rpc as rpc_module
from treasurypilot_worker.chain.rpc import (
    CrossCheck,
    FeeHistory,
    RpcClient,
    RpcError,
    RpcHealthSample,
    RpcProvider,
    RpcResponseError,
    RpcUnavailable,
    SafeConfig,
    build_rpc_client,
    rpc_health_sink,
)


@pytest.fixture(autouse=True)
def no_retry_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rpc_module, "RETRY_BACKOFF_SECONDS", 0)


class FakeProvider:
    """Answers JSON-RPC methods from a table; ``down`` makes every request fail."""

    def __init__(self, answers: dict[str, Any] | None = None, *, down: bool = False) -> None:
        self.answers = answers or {}
        self.down = down
        self.requests: list[tuple[str, Any]] = []

    async def make_request(self, method: str, params: Any) -> dict[str, Any]:
        self.requests.append((method, params))
        if self.down:
            raise ConnectionError("connection refused")
        answer = self.answers[method]
        return {"jsonrpc": "2.0", "id": 1, "result": answer(params) if callable(answer) else answer}


def client(*providers: FakeProvider) -> RpcClient:
    return RpcClient(
        [RpcProvider(f"p{index}", provider) for index, provider in enumerate(providers)]
    )


def test_call_fails_over_to_the_second_provider_when_the_first_is_down() -> None:
    primary = FakeProvider(down=True)
    secondary = FakeProvider({"eth_blockNumber": "0x64"})

    assert asyncio.run(client(primary, secondary).call("eth_blockNumber", [])) == "0x64"
    assert len(primary.requests) == 3  # first attempt + 2 retries


def test_call_raises_rpc_unavailable_when_every_provider_is_down() -> None:
    providers = (FakeProvider(down=True), FakeProvider(down=True))

    with pytest.raises(RpcUnavailable):
        asyncio.run(client(*providers).call("eth_getBalance", ["0x" + "11" * 20, "latest"]))


TX = "0x" + "aa" * 32
BLOCK = "0x" + "b1" * 32
OTHER_BLOCK = "0x" + "b2" * 32


def chain_view(block_hash: str, *, status: str = "0x1") -> FakeProvider:
    receipt = {
        "transactionHash": TX,
        "blockNumber": "0x64",
        "blockHash": block_hash,
        "status": status,
    }
    return FakeProvider(
        {
            "eth_getTransactionReceipt": receipt,
            "eth_getBlockByNumber": {"number": "0x64", "hash": block_hash},
        }
    )


def test_crosscheck_matches_when_both_providers_agree() -> None:
    result = asyncio.run(client(chain_view(BLOCK), chain_view(BLOCK)).crosscheck_receipt(TX))

    assert result is CrossCheck.MATCH


def test_crosscheck_mismatches_when_the_secondary_has_another_block_hash() -> None:
    result = asyncio.run(client(chain_view(BLOCK), chain_view(OTHER_BLOCK)).crosscheck_receipt(TX))

    assert result is CrossCheck.MISMATCH


def test_crosscheck_is_unavailable_while_the_secondary_lags_without_a_receipt() -> None:
    secondary = FakeProvider({"eth_getTransactionReceipt": None})

    result = asyncio.run(client(chain_view(BLOCK), secondary).crosscheck_receipt(TX))

    assert result is CrossCheck.UNAVAILABLE


def test_crosscheck_is_unavailable_when_the_secondary_is_down() -> None:
    result = asyncio.run(client(chain_view(BLOCK), FakeProvider(down=True)).crosscheck_receipt(TX))

    assert result is CrossCheck.UNAVAILABLE


def test_crosscheck_is_unavailable_when_the_primary_is_down() -> None:
    # Failing over would compare the secondary with itself.
    result = asyncio.run(client(FakeProvider(down=True), chain_view(BLOCK)).crosscheck_receipt(TX))

    assert result is CrossCheck.UNAVAILABLE


def test_fee_history_returns_wei_integers() -> None:
    provider = FakeProvider(
        {
            "eth_feeHistory": {
                "oldestBlock": "0x50",
                "baseFeePerGas": ["0x3b9aca00", "0x77359400"],
                "gasUsedRatio": [0.5],
                "reward": [["0x1", "0x2", "0x3"]],
            }
        }
    )

    history = asyncio.run(client(provider, FakeProvider()).fee_history(blocks=1))

    assert history == FeeHistory(
        oldest_block=80,
        base_fee_per_gas=(1_000_000_000, 2_000_000_000),
        gas_used_ratio=(0.5,),
        reward=((1, 2, 3),),
    )
    assert provider.requests == [("eth_feeHistory", ["0x1", "latest", [25, 50, 75]])]


SAFE = "0x" + "5a" * 20
OWNER_A = "0x" + "0a" * 20
OWNER_B = "0x" + "0b" * 20
MODULE = "0x" + "4d" * 20
GUARD = "0x" + "9d" * 20
SENTINEL = "0x" + "00" * 19 + "01"


HEAD = {"number": "0x64", "hash": BLOCK}
PINNED = {"blockHash": BLOCK}


def safe_provider(*, guard: str | None, next_module: str = SENTINEL) -> FakeProvider:
    returns = {
        "0xa0e67e2b": encode(["address[]"], [[OWNER_A, OWNER_B]]),  # getOwners()
        "0xe75235b8": encode(["uint256"], [2]),  # getThreshold()
        "0xcc2f8452": encode(["address[]", "address"], [[MODULE], next_module]),  # getModules...
        "0xaffed0e0": encode(["uint256"], [7]),  # nonce()
    }

    def eth_call(params: list[Any]) -> str:
        assert params[1] == PINNED  # every read is pinned to the head block's hash
        return "0x" + returns[params[0]["data"][:10]].hex()

    def storage(params: list[Any]) -> str:
        assert params[2] == PINNED
        value = guard if params[1].startswith("0x4a204f62") and guard else "0x" + "00" * 20
        return "0x" + "00" * 12 + value.removeprefix("0x")

    return FakeProvider(
        {"eth_getBlockByNumber": HEAD, "eth_call": eth_call, "eth_getStorageAt": storage}
    )


def test_safe_config_reads_one_block() -> None:
    config = asyncio.run(client(safe_provider(guard=GUARD), FakeProvider()).safe_config(SAFE))

    assert config == SafeConfig(
        block_number=100,
        block_hash=BLOCK,
        owners=(OWNER_A, OWNER_B),
        threshold=2,
        modules=(MODULE,),
        guard=GUARD,
        fallback_handler=None,
        nonce=7,
    )


def test_safe_config_rejects_an_address_without_a_safe() -> None:
    provider = FakeProvider({"eth_getBlockByNumber": HEAD, "eth_call": "0x"})

    with pytest.raises(RpcError):
        asyncio.run(client(provider, FakeProvider()).safe_config(SAFE))


def test_safe_config_stops_paging_modules_that_never_end() -> None:
    provider = safe_provider(guard=None, next_module=MODULE)  # the cursor never reaches the end

    with pytest.raises(RpcError, match="did not end"):
        asyncio.run(client(provider, FakeProvider()).safe_config(SAFE))
    assert len(provider.requests) < 50


class Erroring(FakeProvider):
    async def make_request(self, method: str, params: Any) -> dict[str, Any]:
        self.requests.append((method, params))
        return {"jsonrpc": "2.0", "id": 1, "error": {"code": -32005, "message": "rate limited"}}


def test_json_rpc_errors_fail_over_to_the_next_provider() -> None:
    primary = Erroring()
    secondary = FakeProvider({"eth_call": "0x01"})

    assert asyncio.run(client(primary, secondary).call("eth_call", [{}, "latest"])) == "0x01"
    assert len(primary.requests) == 1  # an answer is not retried on the same provider


def test_json_rpc_errors_from_every_provider_raise_the_error() -> None:
    with pytest.raises(RpcResponseError):
        asyncio.run(client(Erroring(), Erroring()).call("eth_call", [{}, "latest"]))


def test_mixed_failures_raise_rpc_unavailable() -> None:
    with pytest.raises(RpcUnavailable):
        asyncio.run(client(Erroring(), FakeProvider(down=True)).call("eth_call", [{}, "latest"]))


def test_every_attempt_is_reported_to_the_health_sink() -> None:
    samples: list[RpcHealthSample] = []

    async def sink(sample: RpcHealthSample) -> None:
        samples.append(sample)

    rpc = RpcClient(
        [
            RpcProvider("alchemy", FakeProvider(down=True)),
            RpcProvider("publicnode", FakeProvider({"eth_blockNumber": "0x64"})),
        ],
        on_health=sink,
    )
    asyncio.run(rpc.call("eth_blockNumber", []))

    assert [(s.provider, s.ok, s.head, s.last_error) for s in samples] == [
        ("alchemy", False, None, "ConnectionError"),
        ("alchemy", False, None, "ConnectionError"),
        ("alchemy", False, None, "ConnectionError"),
        ("publicnode", True, 100, None),
    ]


def test_a_failing_health_sink_does_not_fail_the_call() -> None:
    async def broken_sink(sample: RpcHealthSample) -> None:
        raise OSError("database down")

    rpc = RpcClient(
        [RpcProvider("p0", FakeProvider({"eth_chainId": "0xaa36a7"}))], on_health=broken_sink
    )

    assert asyncio.run(rpc.call("eth_chainId", [])) == "0xaa36a7"


def test_a_slow_health_sink_does_not_stall_the_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rpc_module, "HEALTH_TIMEOUT_SECONDS", 0.01)

    async def stuck_sink(sample: RpcHealthSample) -> None:
        await asyncio.sleep(60)

    rpc = RpcClient(
        [RpcProvider("p0", FakeProvider({"eth_chainId": "0xaa36a7"}))], on_health=stuck_sink
    )

    assert asyncio.run(asyncio.wait_for(rpc.call("eth_chainId", []), 1)) == "0xaa36a7"


def test_programming_errors_are_not_retried() -> None:
    class Broken(FakeProvider):
        async def make_request(self, method: str, params: Any) -> dict[str, Any]:
            self.requests.append((method, params))
            raise TypeError("bad params")

    broken = Broken()

    with pytest.raises(TypeError):
        asyncio.run(client(broken, FakeProvider()).call("eth_chainId", []))
    assert len(broken.requests) == 1


def test_build_rpc_client_expands_keys_but_names_providers_by_host() -> None:
    rpc = build_rpc_client(
        ["https://eth-sepolia.g.alchemy.com/v2/${ALCHEMY_KEY}", "https://sepolia.publicnode.com"],
        environ={"ALCHEMY_KEY": "secret"},
    )

    assert [p.name for p in rpc.providers] == [
        "eth-sepolia.g.alchemy.com",
        "sepolia.publicnode.com",
    ]
    assert rpc.providers[0].transport.endpoint_uri == "https://eth-sepolia.g.alchemy.com/v2/secret"


def test_build_rpc_client_rejects_an_unset_key() -> None:
    with pytest.raises(ValueError, match="ALCHEMY_KEY"):
        build_rpc_client(["https://x.example/v2/${ALCHEMY_KEY}"], environ={})


def test_rpc_health_sink_inserts_one_row_per_sample() -> None:
    class FakePool:
        def __init__(self) -> None:
            self.executed: list[tuple[Any, ...]] = []

        async def execute(self, query: str, *args: Any) -> None:
            self.executed.append((query, *args))

    pool = FakePool()
    asyncio.run(
        rpc_health_sink(pool)(RpcHealthSample("alchemy", False, 4000, None, "TimeoutError"))
    )

    query, *values = pool.executed[0]
    assert query.startswith("INSERT INTO rpc_health (provider, ok, latency_ms, head, last_error)")
    assert values == ["alchemy", False, 4000, None, "TimeoutError"]
