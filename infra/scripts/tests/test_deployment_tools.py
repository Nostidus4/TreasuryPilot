from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest

from treasurypilot_core.attestations import PAYMENT_RECEIPT_SCHEMA, PAYMENT_RECEIPT_SCHEMA_UID


def load_script(name: str) -> ModuleType:
    directory = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(name, directory / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with patch.object(sys, "path", [str(directory), *sys.path]):
        spec.loader.exec_module(module)
    return module


def prediction_values() -> dict[str, object]:
    publisher = load_script("publish_manifest")
    result: dict[str, object] = {
        "chainId": 31337,
        "deploymentStatus": "predicted",
        "aavePool": "0x" + "00" * 20,
        "aToken": "0x" + "00" * 20,
        "assetDecimals": 6,
        "operationalWalletCount": 2,
        "demoOwner": "0x" + "ff" * 20,
        "easAttester": "0x" + "ee" * 20,
        "easSchemaUid": PAYMENT_RECEIPT_SCHEMA_UID,
        "easSchemaRegistered": False,
    }
    for index, field in enumerate(publisher.RUNTIME_CONTRACTS, start=1):
        result[field] = "0x" + f"{index:040x}"
        result[field + "CodeHash"] = "0x" + "ab" * 32
    return result


def mock_deployment_rpc(
    monkeypatch: pytest.MonkeyPatch, publisher: ModuleType, values: dict[str, object]
) -> None:
    def run_cast(arguments: list[str]) -> str:
        if arguments[0] == "chain-id":
            return str(values["chainId"])
        if arguments[0] == "block-number":
            return "42"
        if arguments[0] == "code":
            return "0x6000"
        if arguments[0] == "keccak":
            return "0x" + "ab" * 32
        raise AssertionError(f"Unexpected command: {arguments[0]}")

    def read_scalar(
        contract: str, signature: str, arguments: list[str], rpc_url: str, block: str = "latest"
    ) -> object:
        identity = {
            "safeT()(address)": values["safeT"],
            "asset()(address)": values["asset"],
            "aavePool()(address)": values["aavePool"],
            "aToken()(address)": values["aToken"],
            "implementation()(address)": values["implementation"],
            "masterCopy()(address)": values["safeSingleton"],
            "decimals()(uint8)": "6",
            "getThreshold()(uint256)": "1",
            "getOwners()(address[])": [values["demoOwner"]],
            "isModuleEnabled(address)(bool)": True,
            "isOperational(address)(bool)": True,
            "operationalList()(address[])": [values["safeO1"]]
            if values["operationalWalletCount"] == 1
            else [values["safeO1"], values["safeO2"]],
        }
        assert block == "42"
        return identity[signature]

    monkeypatch.setattr(publisher, "run_cast", run_cast)
    monkeypatch.setattr(publisher, "read_scalar", read_scalar)
    monkeypatch.setattr(publisher, "verify_schema", lambda *args: None)


def test_publisher_requires_mined_code_and_preserves_manifest_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    publisher = load_script("publish_manifest")
    values = prediction_values()
    prediction = tmp_path / "prediction.json"
    prediction.write_text(json.dumps(values))
    manifest = tmp_path / "manifest.json"
    original = '{"chainId":31337,"deploymentStatus":"configured_only","metadata":"keep"}'
    manifest.write_text(original)
    mock_deployment_rpc(monkeypatch, publisher, values)
    original_cast = publisher.run_cast
    monkeypatch.setattr(
        publisher, "run_cast", lambda args: "0x" if args[0] == "code" else original_cast(args)
    )
    with pytest.raises(ValueError, match="No mined runtime code"):
        publisher.publish(prediction, manifest, "http://local.invalid")
    assert manifest.read_text() == original


def test_publisher_checks_runtime_hash_and_preserves_manifest_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    publisher = load_script("publish_manifest")
    values = prediction_values()
    values["moduleCodeHash"] = "0x" + "cd" * 32
    prediction = tmp_path / "prediction.json"
    prediction.write_text(json.dumps(values))
    manifest = tmp_path / "manifest.json"
    original = '{"chainId":31337,"deploymentStatus":"configured_only"}'
    manifest.write_text(original)
    mock_deployment_rpc(monkeypatch, publisher, values)
    with pytest.raises(ValueError, match="runtime hash differs for module"):
        publisher.publish(prediction, manifest, "http://local.invalid")
    assert manifest.read_text() == original


@pytest.mark.parametrize("signature", ["safeT()(address)", "isModuleEnabled(address)(bool)"])
def test_publisher_rejects_wrong_module_identity_or_enablement(
    signature: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    publisher = load_script("publish_manifest")
    values = prediction_values()
    prediction = tmp_path / "prediction.json"
    prediction.write_text(json.dumps(values))
    manifest = tmp_path / "manifest.json"
    mock_deployment_rpc(monkeypatch, publisher, values)
    original_read = publisher.read_scalar
    monkeypatch.setattr(
        publisher,
        "read_scalar",
        lambda contract, sig, *args: (
            False if sig == "isModuleEnabled(address)(bool)" else "0x" + "ee" * 20
        )
        if sig == signature
        else original_read(contract, sig, *args),
    )
    with pytest.raises(ValueError, match="does not match|enablement"):
        publisher.publish(prediction, manifest, "http://local.invalid")
    assert not manifest.exists()


def test_publisher_merges_metadata_only_after_all_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    publisher = load_script("publish_manifest")
    values = prediction_values()
    prediction = tmp_path / "prediction.json"
    prediction.write_text(json.dumps(values))
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"chainId":31337,"metadata":"keep"}')
    mock_deployment_rpc(monkeypatch, publisher, values)
    publisher.publish(prediction, manifest, "http://local.invalid")
    published = json.loads(manifest.read_text())
    assert published["deploymentStatus"] == "deployed"
    assert published["verifiedAtBlock"] == 42
    assert published["easSchemaRegistered"] is True
    assert published["metadata"] == "keep"
    assert json.loads(prediction.read_text())["deploymentStatus"] == "predicted"


def test_schema_only_publication_keeps_uid_scalar_and_preserves_deployment_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    publisher = load_script("publish_manifest")
    values = prediction_values()
    prediction = tmp_path / "prediction.json"
    prediction.write_text(json.dumps(values))
    manifest = tmp_path / "manifest.json"
    original = {
        "chainId": 31337,
        "easRegistry": values["easRegistry"],
        "deploymentStatus": "configured_only",
        "module": None,
        "deploymentSource": {"commit": "keep"},
    }
    manifest.write_text(json.dumps(original))
    mock_deployment_rpc(monkeypatch, publisher, values)
    for _ in range(2):
        publisher.publish(prediction, manifest, "http://local.invalid", schema_only=True)
    published = json.loads(manifest.read_text())
    assert published["easSchemaUid"] == PAYMENT_RECEIPT_SCHEMA_UID
    assert published["easSchemaRegistered"] is True
    assert published["module"] is None
    assert published["deploymentStatus"] == "configured_only"
    assert published["deploymentSource"] == original["deploymentSource"]


@pytest.mark.parametrize("corrupt_field", [0, 1, 2, 3])
def test_schema_verification_requires_exact_record(
    corrupt_field: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    helpers = load_script("cast_helpers")
    record: list[object] = [
        PAYMENT_RECEIPT_SCHEMA_UID,
        "0x" + "00" * 20,
        False,
        PAYMENT_RECEIPT_SCHEMA,
    ]
    monkeypatch.setattr(helpers, "read_scalar", lambda *args: record)
    helpers.verify_schema("0x" + "11" * 20, PAYMENT_RECEIPT_SCHEMA_UID, "http://mock.invalid")
    record[corrupt_field] = [
        "0x" + "ab" * 32,
        "0x" + "11" * 20,
        True,
        PAYMENT_RECEIPT_SCHEMA + ",bool extra",
    ][corrupt_field]
    with pytest.raises(ValueError, match="exact ABI"):
        helpers.verify_schema("0x" + "11" * 20, PAYMENT_RECEIPT_SCHEMA_UID, "http://mock.invalid")


@pytest.mark.parametrize(
    "mode",
    [
        "unfinalized",
        "reorg",
        "no_finality",
        "finalized",
        "wrapped_finalized",
        "local",
        "wrong_signer",
        "timeout",
        "duplicate",
        "recover",
        "locked",
        "changed_payload",
    ],
)
def test_attester_requires_finality_and_canonical_block_before_send(
    mode: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = load_script("attest_receipt")
    request_id = "0x" + "01" * 32
    payee = "0x" + "22" * 20
    module = "0x" + "33" * 20
    block_hash = "0x" + "ab" * 32
    topic = "0x" + "cd" * 32
    values = {
        "requestId": request_id,
        "invoiceHash": "0x" + "02" * 32,
        "approvalHash": "0x" + "03" * 32,
        "planHash": "0x" + "04" * 32,
        "payTxHash": "0x" + "05" * 32,
        "payee": payee,
        "amount": 100,
        "policyVersion": "0x" + "06" * 32,
    }
    manifest = {
        "chainId": 31337 if mode == "local" else 11155111,
        "module": module,
        "eas": "0x" + "44" * 20,
        "easRegistry": "0x" + "55" * 20,
        "easSchemaUid": PAYMENT_RECEIPT_SCHEMA_UID,
        "easAttester": "0x" + "66" * 20,
    }
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps(values))
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    transaction = {
        "status": "0x1",
        "blockNumber": "0x64",
        "blockHash": block_hash,
        "logs": [
            {
                "address": module,
                "topics": [topic, request_id, "0x" + "07" * 32, "0x" + "08" * 32],
                "data": "0x"
                + "00" * 32
                + "00" * 12
                + payee[2:]
                + (100).to_bytes(32, "big").hex()
                + "00" * 96,
            }
        ],
    }
    calls: list[list[str]] = []

    def run_cast(arguments: list[str]) -> str:
        calls.append(arguments)
        if arguments[0] == "chain-id":
            return str(manifest["chainId"])
        if arguments[0] == "wallet":
            return "0x" + ("77" if mode == "wrong_signer" else "66") * 20
        if arguments[0] == "call":
            return "true"
        if arguments[0] == "receipt":
            return json.dumps(transaction)
        if arguments[0] == "keccak":
            return topic
        if arguments[0] == "block-number":
            return "112"
        if arguments[0] == "block":

            def block_response(value: dict[str, object]) -> str:
                if mode == "wrapped_finalized":
                    return json.dumps({"schema_version": 1, "success": True, "data": value})
                return json.dumps(value)

            if arguments[1] == "finalized":
                if mode == "no_finality":
                    raise RuntimeError("Finality unavailable")
                return block_response(
                    {"number": 99 if mode == "unfinalized" else 100, "hash": block_hash}
                )
            return block_response(
                {"number": 100, "hash": "0x" + "ef" * 32 if mode == "reorg" else block_hash}
            )
        if arguments[0] == "send":
            if mode == "timeout":
                raise RuntimeError("Ambiguous RPC timeout")
            return json.dumps(
                {
                    "transactionHash": "0x" + "99" * 32,
                    "status": "0x1",
                    "logs": [
                        {
                            "address": manifest["eas"],
                            "topics": [
                                topic,
                                "0x" + payee[2:].zfill(64),
                                "0x" + ("66" * 20).zfill(64),
                                PAYMENT_RECEIPT_SCHEMA_UID,
                            ],
                            "data": "0x" + "88" * 32,
                        }
                    ],
                }
            )
        raise AssertionError(f"Unexpected command: {arguments[0]}")

    monkeypatch.setattr(helper, "run_cast", run_cast)
    monkeypatch.setattr(helper, "verify_schema", lambda *args: None)
    monkeypatch.setattr(helper, "verify_existing_receipt", lambda *args: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "attest_receipt.py",
            "--receipt",
            str(receipt),
            "--manifest",
            str(manifest_path),
            "--broadcast",
            "--rpc-url",
            "http://mock.invalid",
            "--keystore",
            "synthetic-keystore",
            "--password-file",
            "synthetic-password",
            "--confirmations",
            "0",
            "--journal",
            str(tmp_path / "receipt-journal.json"),
        ],
    )
    if mode in {
        "finalized",
        "wrapped_finalized",
        "local",
        "duplicate",
        "recover",
        "changed_payload",
    }:
        helper.main()
        assert any(call[0] == "send" for call in calls)
        assert any(call[:2] == ["block", "finalized"] for call in calls) == (mode != "local")
        if mode == "duplicate":
            helper.main()
            assert len([call for call in calls if call[0] == "send"]) == 1
        if mode == "recover":
            journal = tmp_path / "receipt-journal.json"
            stored = json.loads(journal.read_text())
            stored.pop("attestationUid")
            stored["state"] = "submitting"
            journal.write_text(json.dumps(stored))
            with patch.object(sys, "argv", [*sys.argv, "--existing-uid", "0x" + "88" * 32]):
                helper.main()
            assert json.loads(journal.read_text())["state"] == "confirmed"
            helper.main()
            assert len([call for call in calls if call[0] == "send"]) == 1
        if mode == "changed_payload":
            values["planHash"] = "0x" + "ff" * 32
            receipt.write_text(json.dumps(values))
            with pytest.raises(ValueError, match="does not match"):
                helper.main()
            assert len([call for call in calls if call[0] == "send"]) == 1
    elif mode == "locked":
        (tmp_path / "receipt-journal.json.lock").write_text("another worker")
        with pytest.raises(ValueError, match="already locked"):
            helper.main()
        assert not any(call[0] == "send" for call in calls)
    elif mode == "timeout":
        with pytest.raises(RuntimeError, match="timeout"):
            helper.main()
        with pytest.raises(ValueError, match="uncertain"):
            helper.main()
        assert len([call for call in calls if call[0] == "send"]) == 1
        assert json.loads((tmp_path / "receipt-journal.json").read_text())["state"] == "submitting"
    else:
        with pytest.raises(
            (ValueError, RuntimeError), match="finalized|canonical|Finality|keystore"
        ):
            helper.main()
        assert not any(call[0] == "send" for call in calls)


def test_cast_passes_large_bytecode_on_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    helpers = load_script("cast_helpers")
    code = "0x" + "60" * 24000
    observed: dict[str, object] = {}

    def subprocess_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        observed.update(command=command, **kwargs)
        return SimpleNamespace(returncode=0, stdout="0x" + "ab" * 32)

    monkeypatch.setattr(helpers.subprocess, "run", subprocess_run)
    assert helpers.run_cast(["keccak", code]) == "0x" + "ab" * 32
    assert observed["command"] == ["cast", "keccak"]
    assert observed["input"] == code


def test_cast_moves_keyed_rpc_url_to_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    helpers = load_script("cast_helpers")
    observed: dict[str, object] = {}
    rpc = "https://provider.invalid/public-test-api-key"

    def subprocess_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        observed.update(command=command, **kwargs)
        return SimpleNamespace(returncode=0, stdout="11155111")

    monkeypatch.setattr(helpers.subprocess, "run", subprocess_run)
    assert helpers.run_cast(["chain-id", "--rpc-url", rpc]) == "11155111"
    assert observed["command"] == ["cast", "chain-id"]
    environment = observed["env"]
    assert isinstance(environment, dict) and environment["ETH_RPC_URL"] == rpc


@pytest.mark.parametrize(
    "field",
    ["asset", "aavePool", "eas", "easRegistry", "safeSingleton", "safeProxyFactory", "multiSend"],
)
def test_sepolia_publisher_rejects_infrastructure_drift(
    field: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    publisher = load_script("publish_manifest")
    values = prediction_values()
    values.update(chainId=11155111, aavePool="0x" + "aa" * 20)
    manifest = tmp_path / "manifest.json"
    original = json.dumps(values)
    manifest.write_text(original)
    values[field] = "0x" + "bb" * 20
    prediction = tmp_path / "prediction.json"
    prediction.write_text(json.dumps(values))
    monkeypatch.setattr(
        publisher, "run_cast", lambda args: "11155111" if args[0] == "chain-id" else "42"
    )
    with pytest.raises(ValueError, match="reviewed Sepolia"):
        publisher.publish(prediction, manifest, "http://mock.invalid")
    assert manifest.read_text() == original


@pytest.mark.parametrize("index", [0, 1, 3, 4, 5, 6, 7, 8, 9])
def test_existing_receipt_requires_trusted_identity_and_exact_payload(
    index: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    from treasurypilot_core.attestations import PaymentReceipt

    helper = load_script("attest_receipt")
    receipt = PaymentReceipt(
        "0x" + "01" * 32,
        "0x" + "02" * 32,
        "0x" + "03" * 32,
        "0x" + "04" * 32,
        "0x" + "05" * 32,
        "0x" + "22" * 20,
        100,
        "0x" + "06" * 32,
    )
    uid = "0x" + "88" * 32
    attester = "0x" + "66" * 20
    record: list[object] = [
        uid,
        PAYMENT_RECEIPT_SCHEMA_UID,
        "100",
        "0",
        "0",
        "0x" + "00" * 32,
        receipt.payee,
        attester,
        False,
        "0x" + receipt.encode().hex(),
    ]
    monkeypatch.setattr(helper, "read_scalar", lambda *args: record)
    helper.verify_existing_receipt(
        "0x" + "44" * 20, uid, PAYMENT_RECEIPT_SCHEMA_UID, attester, receipt, "http://mock.invalid"
    )
    record[index] = True if index == 8 else "0x" + "ff" * 32
    with pytest.raises(ValueError, match="trusted attester"):
        helper.verify_existing_receipt(
            "0x" + "44" * 20,
            uid,
            PAYMENT_RECEIPT_SCHEMA_UID,
            attester,
            receipt,
            "http://mock.invalid",
        )


@pytest.mark.parametrize(
    "response",
    [
        None,
        {"schema_version": 1, "success": False},
        {"schema_version": 1, "success": True, "data": None},
    ],
)
def test_cast_rejects_missing_or_failed_block_objects(response: object) -> None:
    helpers = load_script("cast_helpers")
    with pytest.raises(ValueError, match="Cast returned"):
        helpers.json_object(json.dumps(response))


@pytest.mark.parametrize(
    "field,bad_value",
    [("assetDecimals", 18), ("operationalWalletCount", 2), ("aToken", "0x" + "bb" * 20)],
)
def test_reviewed_sepolia_metadata_mismatch_preserves_manifest(
    field: str, bad_value: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    publisher = load_script("publish_manifest")
    values = prediction_values()
    values.update(
        chainId=11155111,
        operationalWalletCount=1,
        safeO2="0x" + "00" * 20,
        aavePool="0x" + "aa" * 20,
        aToken="0x" + "cc" * 20,
    )
    reviewed = dict(values)
    reviewed[field] = bad_value
    manifest = tmp_path / "manifest.json"
    original = json.dumps(reviewed)
    manifest.write_text(original)
    prediction = tmp_path / "prediction.json"
    prediction.write_text(json.dumps(values))
    mock_deployment_rpc(monkeypatch, publisher, values)
    with pytest.raises(ValueError, match="reviewed Sepolia configuration"):
        publisher.publish(prediction, manifest, "http://mock.invalid")
    assert manifest.read_text() == original


@pytest.mark.parametrize("mode", ["valid", "extra_wallet", "nonzero_o2", "bad_count"])
def test_sepolia_single_wallet_profile(
    mode: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    publisher = load_script("publish_manifest")
    values = prediction_values()
    values.update(chainId=11155111, operationalWalletCount=1, safeO2="0x" + "00" * 20)
    mock_deployment_rpc(monkeypatch, publisher, values)
    original_read = publisher.read_scalar

    def read_scalar(contract: str, signature: str, *args: object) -> object:
        if mode == "extra_wallet" and signature == "operationalList()(address[])":
            return [values["safeO1"], "0x" + "dd" * 20]
        return original_read(contract, signature, *args)

    monkeypatch.setattr(publisher, "read_scalar", read_scalar)
    if mode == "nonzero_o2":
        values["safeO2"] = "0x" + "dd" * 20
    if mode == "bad_count":
        values["operationalWalletCount"] = 2
    if mode == "valid":
        publisher.verify_deployment(values, "http://mock.invalid", "42")
    else:
        with pytest.raises(ValueError, match="wallet count|wallet list|safeO2"):
            publisher.verify_deployment(values, "http://mock.invalid", "42")


@pytest.mark.parametrize("status", [True, False, "0x0", 0, None])
def test_receipt_uid_rejects_failed_or_invalid_status(status: object) -> None:
    helper = load_script("attest_receipt")
    with pytest.raises(ValueError, match="did not succeed"):
        helper.receipt_uid({"status": status}, "", "", "", "")
