// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;
import {SafeTestHelper} from "../helpers/SafeTestHelper.sol";
import {ECDSA} from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";

/// @notice Test-only EIP-712 oracle for the policy/signer boundary; no module execution authority.
contract PlanAttestationVectorsTest is SafeTestHelper {
    bytes32 internal constant TYPEHASH = keccak256(
        "PlanAttestation(bytes32 planHash,bytes32 requestId,bytes32[] stepIds,bytes32 policyVersion,address executor,uint64 validUntil,uint256 nonce,bytes32 evidenceDigest)"
    );

    function testPolicyVectorWithTwoSteps() external {
        _verify("test/vectors/plan-attestation.json");
    }

    function testPolicyVectorWithEmptyArrayAndLargeNonce() external {
        _verify("test/vectors/plan-attestation-empty.json");
    }

    function _verify(string memory file) internal {
        string memory json = vm.readFile(file);
        bytes32[] memory stepIds = vm.parseJsonBytes32Array(json, ".message.stepIds");
        bytes32 structHash = _structHash(json, stepIds);
        bytes32 domainType =
            keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)");
        uint256 chain = vm.parseJsonUint(json, ".domain.chainId");
        address target = vm.parseJsonAddress(json, ".domain.verifyingContract");
        bytes32 domain =
            keccak256(abi.encode(domainType, keccak256("TreasuryPilot Policy"), keccak256("1"), chain, target));
        bytes32 approvalDomain =
            keccak256(abi.encode(domainType, keccak256("TreasuryPilot"), keccak256("1"), chain, target));
        bytes32 digest = keccak256(abi.encodePacked(hex"1901", domain, structHash));
        require(TYPEHASH == vm.parseJsonBytes32(json, ".typeHash"), "policy type hash");
        require(structHash == vm.parseJsonBytes32(json, ".structHash"), "policy struct hash");
        require(domain == vm.parseJsonBytes32(json, ".domainSeparator"), "policy domain");
        require(digest == vm.parseJsonBytes32(json, ".digest"), "policy digest");
        bytes memory signature = vm.parseJsonBytes(json, ".signature");
        address signer = vm.parseJsonAddress(json, ".signer");
        require(ECDSA.recover(digest, signature) == signer, "policy signer");
        require(
            ECDSA.recover(keccak256(abi.encodePacked(hex"1901", approvalDomain, structHash)), signature) != signer,
            "domain separation"
        );
        if (stepIds.length > 0) {
            // The signature must stop verifying once a step changes, not just the hash.
            stepIds[0] = bytes32(uint256(stepIds[0]) ^ 1);
            bytes32 tampered = keccak256(abi.encodePacked(hex"1901", domain, _structHash(json, stepIds)));
            require(ECDSA.recover(tampered, signature) != signer, "steps bound");
        }
    }

    function _structHash(string memory json, bytes32[] memory stepIds) internal pure returns (bytes32) {
        return keccak256(
            abi.encode(
                TYPEHASH,
                vm.parseJsonBytes32(json, ".message.planHash"),
                vm.parseJsonBytes32(json, ".message.requestId"),
                keccak256(abi.encodePacked(stepIds)),
                vm.parseJsonBytes32(json, ".message.policyVersion"),
                vm.parseJsonAddress(json, ".message.executor"),
                uint64(vm.parseJsonUint(json, ".message.validUntil")),
                vm.parseJsonUint(json, ".message.nonce"),
                vm.parseJsonBytes32(json, ".message.evidenceDigest")
            )
        );
    }
}
