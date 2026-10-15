from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
import scenario  # noqa: E402
import scenario_steps  # noqa: E402

from treasurypilot_api.audit.evidence import EvidenceBundle  # noqa: E402

TX = "0x" + "ab" * 32


class FakeChain:
    """Just enough JSON-RPC for the pause scenario."""

    def __init__(self, chain_id: int = 31337) -> None:
        self.chain_id, self.status, self.saved = chain_id, 0, 0

    def __call__(self, _url: str, method: str, params: list[Any]) -> Any:
        if method == "eth_chainId":
            return hex(self.chain_id)
        if method == "evm_snapshot":
            self.saved = self.status
            return "0x1"
        if method == "evm_revert":
            self.status = self.saved
            return True
        if method == "eth_getCode":
            return "0x6001"
        if method == "eth_call":
            return "0x" + self.status.to_bytes(32, "big").hex()
        if method == "eth_sendTransaction":
            self.status = 1
            return TX
        if method == "eth_getTransactionReceipt":
            return {
                "status": "0x1", "transactionHash": TX, "blockNumber": "0x5", "gasUsed": "0x5208",
                "effectiveGasPrice": "0x3b9aca00",
            }  # fmt: skip
        raise AssertionError(method)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scenario_steps.time, "sleep", lambda _s: None)


def patch_rpc(monkeypatch: pytest.MonkeyPatch, chain: FakeChain) -> None:
    monkeypatch.setattr(scenario, "rpc", chain)
    monkeypatch.setattr(scenario_steps, "rpc", chain)


@pytest.fixture
def manifest(tmp_path: Path) -> Path:
    path = tmp_path / "manifest" / "31337.json"
    path.parent.mkdir()
    addresses = {
        k: "0x" + f"{i:02x}" * 20
        for i, k in enumerate(("module", "safeT", "safeO1", "asset", "aavePool", "aToken"), 1)
    }
    path.write_text(json.dumps(addresses))
    return path


def test_list_shows_all_named_scenarios(capsys: pytest.CaptureFixture[str]) -> None:
    assert scenario.main(["list"]) == 0
    rows = [line.split() for line in capsys.readouterr().out.splitlines()]
    assert {r[1] for r in rows} >= {f"D{i}" for i in range(1, 11)} | {"M19-D5"}
    assert {r[0] for r in rows} >= {"unexpected-outflow", "fee-spike", "demo-main", "pause"}
    assert all(r[-1] == "runnable" for r in rows)


def test_invalid_scenario_file_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "x.yaml").write_text("name: y\nchain_id: 1\n")
    with pytest.raises(scenario.ScenarioError, match="file name"):
        scenario.load_scenarios(tmp_path)
    (tmp_path / "x.yaml").write_text(
        "name: x\nchain_id: 31337\nrequires: [anvil]\nmust_show: [a]\nsteps: [nope]\n"
    )
    with pytest.raises(scenario.ScenarioError, match="unknown step"):
        scenario.load_scenarios(tmp_path)


def _write(tmp_path: Path, body: str) -> Path:
    (tmp_path / "x.yaml").write_text(f"name: x\nmust_show: [a]\n{body}")
    return tmp_path


def test_scenario_file_validation(tmp_path: Path) -> None:
    for body, message in (
        ("chain_id: 1\nrequires: [anvil]\n", "not in the scenario allowlist"),
        ("chain_id: 31337\nrequires: [anvil]\n", "non-empty `steps`"),
        ("chain_id: 31337\nrequires: [anvil]\nsteps: []\n", "non-empty `steps`"),
        ("chain_id: 31337\nrequires: [anvil, plannr]\n", "unknown capability"),
    ):
        with pytest.raises(scenario.ScenarioError, match=message):
            scenario.load_scenarios(_write(tmp_path, body))


def test_mainnet_yaml_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    directory = _write(tmp_path, "chain_id: 1\nrequires: [anvil]\n")
    assert scenario.main(["--scenarios-dir", str(directory), "list"]) == scenario.EXIT_FAILED
    assert "not in the scenario allowlist" in capsys.readouterr().err
    assert scenario.main(["--scenarios-dir", str(directory), "run", "x"]) == scenario.EXIT_FAILED


def test_yaml_rpc_chain_mismatch_sends_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, manifest: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    directory = _write(tmp_path, "chain_id: 11155111\nrequires: [anvil]\nsteps: [guardian_pause]\n")
    chain = FakeChain(31337)
    patch_rpc(monkeypatch, chain)
    code = scenario.main(
        ["--scenarios-dir", str(directory), "run", "x", "--out", str(tmp_path / "out"),
         "--manifest", str(manifest)]
    )  # fmt: skip
    assert code == scenario.EXIT_FAILED and chain.status == 0
    assert "targets chain 11155111" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_guardian_pause_refuses_sepolia(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, manifest: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    directory = _write(tmp_path, "chain_id: 11155111\nrequires: [anvil]\nsteps: [guardian_pause]\n")
    chain = FakeChain(11155111)
    patch_rpc(monkeypatch, chain)
    code = scenario.main(
        ["--scenarios-dir", str(directory), "run", "x", "--out", str(tmp_path / "out"),
         "--manifest", str(manifest)]
    )  # fmt: skip
    assert code == scenario.EXIT_FAILED and chain.status == 0
    assert "chain 31337" in capsys.readouterr().err


def test_unreachable_rpc_message(capsys: pytest.CaptureFixture[str]) -> None:
    code = scenario.main(["run", "pause", "--rpc-url", "http://127.0.0.1:1"])
    assert code == scenario.EXIT_FAILED
    assert "cannot reach RPC" in capsys.readouterr().err


def test_mainnet_chain_id_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    patch_rpc(monkeypatch, FakeChain(chain_id=1))
    assert scenario.main(["run", "pause", "--out", str(tmp_path / "out")]) == scenario.EXIT_FAILED
    assert "refusing to run: RPC serves chain id 1" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_pause_writes_valid_evidence_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, manifest: Path
) -> None:
    chain = FakeChain()
    patch_rpc(monkeypatch, chain)
    code = scenario.main(
        ["run", "pause", "--out", str(tmp_path / "out"), "--manifest", str(manifest)]
    )
    assert code == 0 and chain.status == 0  # state was reset after the run
    (run_dir,) = (tmp_path / "out").iterdir()
    run = json.loads((run_dir / "run.json").read_text())
    bundle = EvidenceBundle.model_validate_json((run_dir / "evidence-bundle.json").read_text())
    assert run["status"] == "PASSED" and run["bundleSha256"] == bundle.sha256
    assert bundle.transactions and bundle.transactions[0].tx_hash == TX
    assert bundle.transactions[0].fee_base_units == str(21000 * 10**9)
    assert run["stateReset"] and chain.status == 0  # reverted, so the scenario can be replayed
    again = ["run", "pause", "--out", str(tmp_path / "out"), "--manifest", str(manifest)]
    assert scenario.main(again) == 0
    # With --keep-state the module stays paused, so a replay fails its precondition.
    assert scenario.main([*again, "--keep-state"]) == 0 and chain.status == 1
    assert scenario.main([*again, "--keep-state"]) == scenario.EXIT_FAILED


@pytest.mark.skipif(
    "TP_TEST_ANVIL_URL" not in os.environ, reason="needs Anvil with `make deploy-local` applied"
)
@pytest.mark.parametrize(
    "name", sorted(p.stem for p in (scenario.REPO_ROOT / "scenarios").glob("*.yaml"))
)
def test_scenario_on_real_anvil(name: str, tmp_path: Path) -> None:
    url = os.environ["TP_TEST_ANVIL_URL"]
    for _ in range(2):  # the state reset makes every scenario replayable on the same deployment
        assert scenario.main(["run", name, "--rpc-url", url, "--out", str(tmp_path)]) == 0
    for run_dir in tmp_path.iterdir():
        bundle = EvidenceBundle.model_validate_json((run_dir / "evidence-bundle.json").read_text())
        assert bundle.status == "VALID"  # blocked-action scenarios mine no transaction
        assert all(t.chain_id == 31337 for t in bundle.transactions or [])
