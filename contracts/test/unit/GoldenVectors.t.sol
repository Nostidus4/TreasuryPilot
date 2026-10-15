// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;
import {TreasuryFixture} from "../helpers/TreasuryFixture.sol";
import {TreasuryPilotModule} from "../../src/TreasuryPilotModule.sol";
import {ITreasuryPilotModule as I} from "../../src/interfaces/ITreasuryPilotModule.sol";
import {PaymentApprovalHash} from "../../src/libraries/PaymentApprovalHash.sol";
import {ECDSA} from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";

contract GoldenVectorsTest is TreasuryFixture {
    function testStandardApprovalVector() external {
        _verify("test/vectors/payment-approval.json");
    }

    function testEarlyApprovalVector() external {
        _verify("test/vectors/payment-approval-early.json");
    }

    function testFiatApprovalVector() external {
        _verify("test/vectors/payment-approval-fiat.json");
    }

    function testLargeIntegerApprovalVector() external {
        _verify("test/vectors/payment-approval-large.json");
    }

    function _verify(string memory path) internal {
        string memory json = vm.readFile(path);
        I.PaymentApproval memory ap;
        ap.requestId = vm.parseJsonBytes32(json, ".message.requestId");
        ap.invoiceHash = vm.parseJsonBytes32(json, ".message.invoiceHash");
        ap.fingerprint = vm.parseJsonBytes32(json, ".message.fingerprint");
        ap.treasury = vm.parseJsonAddress(json, ".message.treasury");
        ap.payingWallet = vm.parseJsonAddress(json, ".message.payingWallet");
        ap.asset = vm.parseJsonAddress(json, ".message.asset");
        ap.payee = vm.parseJsonAddress(json, ".message.payee");
        ap.amount = vm.parseJsonUint(json, ".message.amount");
        ap.earlyAmount = vm.parseJsonUint(json, ".message.earlyAmount");
        ap.earlyPayBy = uint64(vm.parseJsonUint(json, ".message.earlyPayBy"));
        ap.deadline = uint64(vm.parseJsonUint(json, ".message.deadline"));
        ap.termsHash = vm.parseJsonBytes32(json, ".message.termsHash");
        ap.expiry = uint64(vm.parseJsonUint(json, ".message.expiry"));
        ap.isFiat = vm.parseJsonBool(json, ".message.isFiat");
        vm.chainId(vm.parseJsonUint(json, ".domain.chainId"));
        // Place the real clone runtime at the vector's fixed verifying address; no initialized state is needed to hash.
        vm.etch(ap.treasury, address(module).code);
        TreasuryPilotModule vectorModule = TreasuryPilotModule(ap.treasury);
        require(PaymentApprovalHash.TYPEHASH == vm.parseJsonBytes32(json, ".typeHash"), "type hash");
        require(PaymentApprovalHash.structHash(ap) == vm.parseJsonBytes32(json, ".structHash"), "struct hash");
        require(vectorModule.domainSeparator() == vm.parseJsonBytes32(json, ".domainSeparator"), "domain hash");
        bytes32 digest = vectorModule.hashApproval(ap);
        require(digest == vm.parseJsonBytes32(json, ".digest"), "digest");
        address signer = vm.parseJsonAddress(json, ".signer");
        bytes memory signature = vm.parseJsonBytes(json, ".signature");
        require(ECDSA.recover(digest, signature) == signer, "recovery");
        require(
            keccak256(abi.encode(signer, signature)) == keccak256(vm.parseJsonBytes(json, ".approverSig")),
            "wire encoding"
        );
    }
}
