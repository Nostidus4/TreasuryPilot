from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
import scenario  # noqa: E402

from treasurypilot_api.audit.evidence import EvidenceBundle  # noqa: E402

TX = "0x" + "ab" * 32


class FakeChain:
    """Just enough JSON-RPC for the pause scenario."""

    def __init__(self, chain_id: int = 31337) -> None:
        self.chain_id, self.status = chain_id, 0

    def __call__(self, _url: str, method: str, params: list[Any]) -> Any:
        if method == "eth_chainId":
            return hex(self.chain_id)
        if method == "eth_getCode":
            return "0x6001"
        if method == "eth_call":
            return hex(self.status)
        if method == "eth_sendTransaction":
            self.status = 1
            return TX
        if method == "eth_getTransactionReceipt":
            return {
                "status": "0x1", "transactionHash": TX, "blockNumber": "0x5", "gasUsed": "0x5208",
                "effectiveGasPrice": "0x3b9aca00",
            }  # fmt: skip
        raise AssertionError(method)


@pytest.fixture
def manifest(tmp_path: Path) -> Path:
    path = tmp_path / "manifest" / "31337.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"module": "0x" + "11" * 20}))
    return path


def test_list_shows_all_named_scenarios(capsys: pytest.CaptureFixture[str]) -> None:
    assert scenario.main(["list"]) == 0
    out = capsys.readouterr().out
    for name in (
        "demo-main", "over-cap-exception", "injected-invoice", "crash-recovery", "pause",
        "unexpected-outflow", "fee-spike",
    ):  # fmt: skip
        assert name in out
    assert "pause" in out and "runnable" in out


def test_invalid_scenario_file_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "x.yaml").write_text("name: y\nchain_id: 1\n")
    with pytest.raises(scenario.ScenarioError, match="file name"):
        scenario.load_scenarios(tmp_path)
    (tmp_path / "x.yaml").write_text(
        "name: x\nchain_id: 31337\nrequires: [anvil]\nmust_show: [a]\nsteps: [nope]\n"
    )
    with pytest.raises(scenario.ScenarioError, match="unknown step"):
        scenario.load_scenarios(tmp_path)


def test_scenario_needing_unmerged_pieces_is_not_runnable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, manifest: Path
) -> None:
    monkeypatch.setattr(scenario, "rpc", FakeChain())
    code = scenario.main(
        ["run", "demo-main", "--out", str(tmp_path / "out"), "--manifest", str(manifest)]
    )
    assert code == scenario.EXIT_NOT_RUNNABLE
    assert not (tmp_path / "out").exists()  # no bundle is faked


def test_mainnet_chain_id_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(scenario, "rpc", FakeChain(chain_id=1))
    assert scenario.main(["run", "pause", "--out", str(tmp_path / "out")]) == scenario.EXIT_FAILED
    assert "refusing to run: RPC serves chain id 1" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_pause_writes_valid_evidence_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, manifest: Path
) -> None:
    chain = FakeChain()
    monkeypatch.setattr(scenario, "rpc", chain)
    code = scenario.main(
        ["run", "pause", "--out", str(tmp_path / "out"), "--manifest", str(manifest)]
    )
    assert code == 0 and chain.status == 1
    (run_dir,) = (tmp_path / "out").iterdir()
    run = json.loads((run_dir / "run.json").read_text())
    bundle = EvidenceBundle.model_validate_json((run_dir / "evidence-bundle.json").read_text())
    assert run["status"] == "PASSED" and run["bundleSha256"] == bundle.sha256
    assert bundle.transactions and bundle.transactions[0].tx_hash == TX
    assert bundle.transactions[0].fee_base_units == str(21000 * 10**9)
    # A second run on the same (now paused) module fails its precondition instead of passing.
    assert (
        scenario.main(["run", "pause", "--out", str(tmp_path / "out"), "--manifest", str(manifest)])
        == scenario.EXIT_FAILED
    )


@pytest.mark.skipif(
    "TP_TEST_ANVIL_URL" not in os.environ, reason="needs Anvil with `make deploy-local` applied"
)
def test_pause_on_real_anvil(tmp_path: Path) -> None:
    url = os.environ["TP_TEST_ANVIL_URL"]
    assert scenario.main(["run", "pause", "--rpc-url", url, "--out", str(tmp_path / "out")]) == 0
    (run_dir,) = (tmp_path / "out").iterdir()
    bundle = EvidenceBundle.model_validate_json((run_dir / "evidence-bundle.json").read_text())
    assert bundle.transactions and bundle.transactions[0].chain_id == 31337
