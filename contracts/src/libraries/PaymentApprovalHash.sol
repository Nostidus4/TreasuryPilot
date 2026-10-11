// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;
import {ITreasuryPilotModule} from "../interfaces/ITreasuryPilotModule.sol";

library PaymentApprovalHash {
    bytes32 internal constant TYPEHASH = keccak256(
        "PaymentApproval(bytes32 requestId,bytes32 invoiceHash,bytes32 fingerprint,address treasury,address payingWallet,address asset,address payee,uint256 amount,uint256 earlyAmount,uint64 earlyPayBy,uint64 deadline,bytes32 termsHash,uint64 expiry)"
    );
    function structHash(ITreasuryPilotModule.PaymentApproval memory approval) internal pure returns (bytes32) {
        return keccak256(abi.encode(TYPEHASH, approval));
    }
}
