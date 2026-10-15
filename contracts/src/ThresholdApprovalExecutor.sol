// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;
import {ITreasuryPilotModule} from "./interfaces/ITreasuryPilotModule.sol";
import {TreasuryPilotErrors as E} from "./libraries/TreasuryPilotErrors.sol";

interface IThresholdModuleState {
    function safeT() external view returns (address);
}

/// @notice Opt-in `mandate.executor` enforcing n-of-m approvals by amount band (F-029, SC-L02). Safe T sets
/// ascending bands `{upTo, k}`; a PAY needs `k` distinct registered approvers to sign the same typed data
/// (`module.hashApproval`). The module already verifies one signature; this contract verifies all of them with
/// `module.verifyApproval` and counts each signer once. The band is chosen by `ap.amount`, the signed maximum,
/// so an early-pay discount or a lower fiat quote can never lower the required k. It lives outside the module
/// (about 100 bytes under EIP-170). Only `pay` is exposed; to combine with other executors, deploy a new
/// executor and call `configureMandate`.
contract ThresholdApprovalExecutor {
    struct Band {
        uint128 upTo; // inclusive upper bound of the band, in asset base units
        uint32 k;
    }

    error NotOwner();
    error BandsNotSet();
    error InvalidBands();
    error InsufficientApprovals(uint256 distinct, uint256 required);

    event BandsSet(Band[] bands);

    ITreasuryPilotModule public immutable module;
    address public immutable operator;
    Band[] internal _bands;

    constructor(ITreasuryPilotModule module_, address operator_) {
        if (address(module_).code.length == 0 || operator_ == address(0)) revert E.InvalidConfiguration();
        module = module_;
        operator = operator_;
    }

    /// @notice Safe T replaces the policy. `upTo` must strictly increase, `k` must not decrease (a larger
    /// payment never needs fewer approvers), the last band must be unbounded and every `k` at least 1.
    function setBands(Band[] calldata nb) external {
        if (msg.sender != IThresholdModuleState(address(module)).safeT()) revert NotOwner();
        uint256 n = nb.length;
        if (n == 0 || nb[n - 1].upTo != type(uint128).max) revert InvalidBands();
        for (uint256 i; i < n; ++i) {
            if (nb[i].k == 0) revert InvalidBands();
            if (i > 0 && (nb[i].upTo <= nb[i - 1].upTo || nb[i].k < nb[i - 1].k)) revert InvalidBands();
        }
        delete _bands;
        for (uint256 i; i < n; ++i) {
            _bands.push(nb[i]);
        }
        emit BandsSet(nb);
    }

    function bands() external view returns (Band[] memory) {
        return _bands;
    }

    /// @notice Required distinct approvers for a payment of `amount`.
    function requiredApprovals(uint256 amount) public view returns (uint256) {
        uint256 n = _bands.length;
        if (n == 0) revert BandsNotSet();
        for (uint256 i; i < n; ++i) {
            if (amount <= _bands[i].upTo) return _bands[i].k;
        }
        return _bands[n - 1].k; // unreachable: the last band is unbounded
    }

    /// @param sigs approver signatures in the module's `approverSig` format; `sigs[0]` is also passed to the module.
    function pay(
        ITreasuryPilotModule.PaymentApproval calldata ap,
        bytes[] calldata sigs,
        bytes32 stepId,
        uint256 paymentAmount
    ) external {
        if (msg.sender != operator) revert E.NotExecutor();
        uint256 required = requiredApprovals(ap.amount);
        address[] memory seen = new address[](sigs.length);
        uint256 distinct;
        for (uint256 i; i < sigs.length; ++i) {
            address signer = module.verifyApproval(ap, sigs[i]); // reverts on a bad or non-approver signature
            bool dup;
            for (uint256 j; j < distinct; ++j) {
                if (seen[j] == signer) {
                    dup = true;
                    break;
                }
            }
            if (!dup) seen[distinct++] = signer;
        }
        if (distinct < required) revert InsufficientApprovals(distinct, required);
        module.pay(ap, sigs[0], stepId, paymentAmount);
    }
}
