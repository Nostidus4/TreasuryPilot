// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;
import {SignatureChecker} from "@openzeppelin/contracts/utils/cryptography/SignatureChecker.sol";
import {ITreasuryPilotModule} from "./interfaces/ITreasuryPilotModule.sol";
import {PlanAttestationHash as H} from "./libraries/PlanAttestationHash.sol";
import {TreasuryPilotErrors as E} from "./libraries/TreasuryPilotErrors.sol";

/// @notice Set as the module's mandate executor so the contract, not the signer service, enforces plan
/// attestations on every plan step (PAY, REFILL, SUPPLY, WITHDRAW). It lives outside the module because the
/// module is within ~100 bytes of the EIP-170 limit. Without a fresh attestation signed by `policySigner`,
/// the module has no other executor, so the step cannot run. Rotate the key or operator by deploying a new
/// executor and calling `configureMandate`.
contract PlanAttestedExecutor {
    ITreasuryPilotModule public immutable module;
    address public immutable operator;
    address public immutable policySigner;
    /// @dev A nonce binds to its planHash on first use; every step of that plan shares it, a new plan cannot.
    mapping(uint256 => bytes32) public nonceBoundTo;

    constructor(ITreasuryPilotModule module_, address operator_, address policySigner_) {
        if (address(module_).code.length == 0 || operator_ == address(0) || policySigner_ == address(0)) {
            revert E.InvalidConfiguration();
        }
        module = module_;
        operator = operator_;
        policySigner = policySigner_;
    }

    function pay(
        ITreasuryPilotModule.PaymentApproval calldata ap,
        bytes calldata approverSig,
        bytes32 stepId,
        H.PlanAttestation calldata att,
        bytes calldata attSig
    ) external {
        _consume(ap.requestId, stepId, att, attSig);
        module.pay(ap, approverSig, stepId);
    }

    function payWithAmount(
        ITreasuryPilotModule.PaymentApproval calldata ap,
        bytes calldata approverSig,
        bytes32 stepId,
        uint256 paymentAmount,
        H.PlanAttestation calldata att,
        bytes calldata attSig
    ) external {
        _consume(ap.requestId, stepId, att, attSig);
        module.payWithAmount(ap, approverSig, stepId, paymentAmount);
    }

    function refill(
        ITreasuryPilotModule.PaymentApproval calldata ap,
        bytes calldata approverSig,
        bytes32 stepId,
        address toWallet,
        uint256 amount,
        H.PlanAttestation calldata att,
        bytes calldata attSig
    ) external {
        _consume(ap.requestId, stepId, att, attSig);
        module.refill(ap, approverSig, stepId, toWallet, amount);
    }

    /// @param requestId 0x0 for a liquidity plan, as in the attestation.
    function supply(
        bytes32 requestId,
        bytes32 stepId,
        uint256 amount,
        H.PlanAttestation calldata att,
        bytes calldata attSig
    ) external {
        _consume(requestId, stepId, att, attSig);
        module.supply(stepId, amount);
    }

    function withdraw(
        bytes32 requestId,
        bytes32 stepId,
        uint256 amount,
        H.PlanAttestation calldata att,
        bytes calldata attSig
    ) external {
        _consume(requestId, stepId, att, attSig);
        module.withdraw(stepId, amount);
    }

    // Not plan steps; the module's own owner authorizations and limits still gate them.
    function borrow(bytes32 planId) external onlyOperator {
        module.borrow(planId);
    }

    function repay(bytes32 planId) external onlyOperator {
        module.repay(planId);
    }

    function swapForGas(bytes32 stepId, uint256 amountIn, uint256 minOut) external onlyOperator {
        module.swapForGas(stepId, amountIn, minOut);
    }

    modifier onlyOperator() {
        if (msg.sender != operator) revert E.NotExecutor();
        _;
    }

    function _consume(bytes32 requestId, bytes32 stepId, H.PlanAttestation calldata att, bytes calldata sig)
        internal
        onlyOperator
    {
        if (
            att.planHash == bytes32(0) || att.executor != msg.sender || att.requestId != requestId
                || !SignatureChecker.isValidSignatureNow(policySigner, H.digest(att, address(module)), sig)
        ) revert E.AttestationInvalid();
        if (block.timestamp > att.validUntil) revert E.AttestationExpired();
        bool found;
        for (uint256 i; i < att.stepIds.length; ++i) {
            if (att.stepIds[i] == stepId) {
                found = true;
                break;
            }
        }
        if (!found) revert E.AttestationInvalid();
        bytes32 bound = nonceBoundTo[att.nonce];
        if (bound == bytes32(0)) nonceBoundTo[att.nonce] = att.planHash;
        else if (bound != att.planHash) revert E.NonceReused();
    }
}
