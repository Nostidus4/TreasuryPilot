// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

/// @notice EIP-712 PlanAttestation, signed under the "TreasuryPilot Policy" domain (M08 section 6.3).
library PlanAttestationHash {
    struct PlanAttestation {
        bytes32 planHash;
        bytes32 requestId;
        bytes32[] stepIds;
        bytes32 policyVersion;
        address executor;
        uint64 validUntil;
        uint256 nonce;
        bytes32 evidenceDigest;
    }

    bytes32 internal constant TYPEHASH = keccak256(
        "PlanAttestation(bytes32 planHash,bytes32 requestId,bytes32[] stepIds,bytes32 policyVersion,address executor,uint64 validUntil,uint256 nonce,bytes32 evidenceDigest)"
    );
    bytes32 internal constant DOMAIN_TYPEHASH =
        keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)");
    bytes32 internal constant NAME_HASH = keccak256("TreasuryPilot Policy");
    bytes32 internal constant VERSION_HASH = keccak256("1");

    function structHash(PlanAttestation memory att) internal pure returns (bytes32) {
        return keccak256(
            abi.encode(
                TYPEHASH,
                att.planHash,
                att.requestId,
                keccak256(abi.encodePacked(att.stepIds)),
                att.policyVersion,
                att.executor,
                att.validUntil,
                att.nonce,
                att.evidenceDigest
            )
        );
    }

    /// @dev `treasury` is the module clone, so an attestation cannot cross treasuries or chains.
    function digest(PlanAttestation memory att, address treasury) internal view returns (bytes32) {
        bytes32 domain = keccak256(abi.encode(DOMAIN_TYPEHASH, NAME_HASH, VERSION_HASH, block.chainid, treasury));
        return keccak256(abi.encodePacked(hex"1901", domain, structHash(att)));
    }
}
