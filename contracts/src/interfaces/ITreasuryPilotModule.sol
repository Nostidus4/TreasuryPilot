// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

/// @notice The fixed authority and asset boundary of one treasury (M04, ADR-019).
interface ITreasuryPilotModule {
    struct Limits {
        uint128 perRequest;
        uint128 daily;
    }

    struct MandateInit {
        uint64 validFrom;
        uint64 expiresAt;
        uint32 payeeCoolingSeconds;
        address executor;
        address guardian;
        Limits pay;
        Limits refill;
        uint32 approvalMaxAge;
        Limits supply;
    }

    struct Mandate {
        uint64 version;
        uint64 validFrom;
        uint64 expiresAt;
        uint32 payeeCoolingSeconds;
        address executor;
        address guardian;
        Limits pay;
        Limits refill;
        uint32 approvalMaxAge;
        Limits supply;
    }

    struct BufferInit {
        address wallet;
        uint256 buffer;
        uint256 target;
    }

    struct PaymentApproval {
        bytes32 requestId;
        bytes32 invoiceHash;
        bytes32 fingerprint;
        address treasury;
        address payingWallet;
        address asset;
        address payee;
        uint256 amount;
        uint256 earlyAmount;
        uint64 earlyPayBy;
        uint64 deadline;
        bytes32 termsHash;
        uint64 expiry;
    }

    struct Payee {
        uint64 activeFrom;
        bool active;
    }

    struct Exception {
        uint128 amount;
        uint64 expiry;
        uint64 mandateVersion;
        address payee;
        bool used;
    }

    struct BorrowAuthorization {
        uint256 amount;
        uint64 expiry;
        uint256 minHealthFactor;
        uint256 maxRateRay;
        bool used;
    }

    struct RepayAuthorization {
        uint256 amount;
        uint64 expiry;
        bool used;
    }
    enum Status {
        Active,
        Paused,
        Revoked
    }
    enum PayeeState {
        Unknown,
        Cooling,
        Active,
        Deactivated
    }

    event MandateConfigured(uint64 version, uint64 expiresAt);
    event ApproversChanged(address[] added, address[] removed);
    event BufferSet(address indexed wallet, uint256 buffer, uint256 target);
    event PayeeAdded(address indexed payee, uint64 activeFrom);
    event PayeeDeactivated(address indexed payee);
    event ExceptionGranted(bytes32 indexed requestId, uint128 amount, address payee, uint64 expiry, uint64 version);
    event ExceptionRevoked(bytes32 indexed requestId);
    event DuplicateAllowed(bytes32 indexed fingerprint, bytes32 indexed requestId);
    event Paused(address indexed by);
    event RequestCancelled(bytes32 indexed requestId, address indexed by);
    event Resumed();
    event Revoked();
    event RefillExecuted(
        bytes32 indexed requestId, bytes32 indexed stepId, address indexed toWallet, uint256 amount, uint256 day
    );
    event PaymentExecuted(
        bytes32 indexed requestId,
        bytes32 indexed stepId,
        bytes32 indexed fingerprint,
        address payingWallet,
        address payee,
        uint256 amount,
        uint256 day,
        bool usedException,
        bool early
    );
    event Supplied(bytes32 indexed stepId, uint256 amount, uint256 day);
    event Withdrawn(bytes32 indexed stepId, uint256 amount, uint256 day);
    event BorrowAuthorized(
        bytes32 indexed planId, uint256 amount, uint64 expiry, uint256 minHealthFactor, uint256 maxRateRay
    );
    event RepayAuthorized(bytes32 indexed planId, uint256 amount, uint64 expiry);
    event Borrowed(bytes32 indexed planId, uint256 amount);
    event Repaid(bytes32 indexed planId, uint256 amount);
    event SwapConfigured(address indexed router, address indexed tokenOut, uint128 perTx, uint128 daily);
    event SwappedForGas(bytes32 indexed stepId, uint256 amountIn, uint256 amountOut, uint256 day);

    /// @notice Called atomically by the factory, exactly once on a clone.
    function initialize(
        address safeT_,
        address asset_,
        address[] calldata operational_,
        MandateInit calldata m,
        address[] calldata approvers,
        BufferInit[] calldata buffers,
        address aavePool_
    ) external;
    /// @notice Only Safe T may change authority, validity or limits; counters persist.
    function configureMandate(MandateInit calldata m) external;
    /// @notice Only Safe T may update the set; at least one approver must remain.
    function setApprovers(address[] calldata add, address[] calldata remove) external;
    /// @notice Only Safe T may set floors and operational targets.
    function setBuffer(address wallet, uint256 buffer, uint256 target) external;
    /// @notice Only Safe T may register a payee; always starts a new cooling period.
    function addPayee(address payee) external;
    /// @notice Only Safe T may deactivate a known payee.
    function deactivatePayee(address payee) external;
    /// @notice Only Safe T may authorize one over-cap payment; no other rule is lifted.
    function grantException(bytes32 requestId, uint128 amount, address payee, uint64 expiry) external;
    /// @notice Only Safe T may remove an exception.
    function revokeException(bytes32 requestId) external;
    /// @notice Only Safe T may authorize one specific request to reuse a fingerprint.
    function allowDuplicate(bytes32 fingerprint, bytes32 requestId) external;
    /// @notice Owner or guardian may pause; repeated pauses are harmless.
    function pause() external;
    /// @notice Only Safe T may resume a paused, non-revoked module.
    function resume() external;
    /// @notice Only Safe T may permanently revoke the module.
    function revoke() external;
    /// @notice Safe T or a current approver may permanently cancel an unpaid request.
    function cancelRequest(bytes32 requestId) external;
    /// @notice Executor pays exactly the signed payment option via the operational Safe.
    function pay(PaymentApproval calldata ap, bytes calldata approverSig, bytes32 stepId) external;
    /// @notice Executor refills only the approved operational wallet, once per request.
    function refill(
        PaymentApproval calldata ap,
        bytes calldata approverSig,
        bytes32 stepId,
        address toWallet,
        uint256 amount
    ) external;
    /// @notice Executor supplies the sole asset to the sole pool, preserving Safe T's floor.
    function supply(bytes32 stepId, uint256 amount) external;
    /// @notice Executor withdraws only into Safe T.
    function withdraw(bytes32 stepId, uint256 amount) external;
    /// @notice Only Safe T may authorize one borrowing of the exact approved plan hash.
    function authorizeBorrow(bytes32 planId, uint256 amount, uint64 expiry, uint256 minHealthFactor, uint256 maxRateRay)
        external;
    /// @notice Only Safe T may authorize one repayment of the exact approved plan hash.
    function authorizeRepay(bytes32 planId, uint256 amount, uint64 expiry) external;
    /// @notice Executor consumes the owner grant once, checking rate and health factor.
    function borrow(bytes32 planId) external;
    /// @notice Executor consumes the owner grant once and repays variable debt only.
    function repay(bytes32 planId) external;
    /// @notice Only Safe T may configure a test router and ERC20 output pair; no native transfers.
    function configureSwap(address router, address tokenOut, Limits calldata limits) external;
    /// @notice Executor swaps via the sole approved test pair, subject to budget and minOut.
    function swapForGas(bytes32 stepId, uint256 amountIn, uint256 minOut) external;
    function mandate() external view returns (Mandate memory);
    function operationalList() external view returns (address[] memory);
    function payeeStatus(address payee) external view returns (PayeeState state, uint64 activeFrom);
    function usedToday(uint8 action) external view returns (uint256);
    function remainingToday(uint8 action) external view returns (uint256);
    function domainSeparator() external view returns (bytes32);
    function hashApproval(PaymentApproval calldata ap) external view returns (bytes32);
    /// @notice Signature wire format is abi.encode(approver, signature), including ERC-1271.
    function verifyApproval(PaymentApproval calldata ap, bytes calldata approverSig) external view returns (address);
}
