// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {ITreasuryPilotModule} from "./interfaces/ITreasuryPilotModule.sol";
import {TreasuryPilotErrors as E} from "./libraries/TreasuryPilotErrors.sol";

/// @dev Public getters of the module's storage that the module interface does not list.
interface IModuleState {
    function safeT() external view returns (address);
    function asset() external view returns (address);
    function isOperational(address wallet) external view returns (bool);
    function requestPaid(bytes32 requestId) external view returns (bool);
    function requestCancelled(bytes32 requestId) external view returns (bool);
}

/// @notice Set as the module's mandate executor so funds committed to registered requests (F-028, BR-035)
/// cannot be spent by another request. Reserved (R) funds belong to an approved request; held (L) funds belong
/// to a request whose execution started. Moving R to L never changes the wallet's committed total, so nothing
/// is counted twice. A hold is released only on a known outcome, never by a timeout. It lives outside the
/// module (about 100 bytes under EIP-170), so the module ABI and storage layout are unchanged. Every spend
/// goes through this contract, which checks `balance >= bufferOf + committed` after the module call.
contract ReserveHoldExecutor {
    struct Commitment {
        address asset;
        address wallet;
        uint128 reserved;
        uint128 held;
    }

    error NotOwner();
    error AlreadyRegistered();
    error NothingToHold();
    error NotRegistered();
    error ReleaseNotAllowed();
    error InsufficientUncommitted();
    error CommittedFundsBreach();

    event Reserved(bytes32 indexed requestId, address indexed asset, address indexed wallet, uint256 amount);
    event HoldStarted(bytes32 indexed requestId, uint256 amount);
    event Released(bytes32 indexed requestId, uint256 reserved, uint256 held, bool byOwner);

    ITreasuryPilotModule public immutable module;
    address public immutable operator;
    mapping(bytes32 => Commitment) public commitments;
    /// @dev asset => wallet => total reserved (R) / total held (L).
    mapping(address => mapping(address => uint256)) public reservedOf;
    mapping(address => mapping(address => uint256)) public heldOf;

    constructor(ITreasuryPilotModule module_, address operator_) {
        if (address(module_).code.length == 0 || operator_ == address(0)) revert E.InvalidConfiguration();
        module = module_;
        operator = operator_;
    }

    modifier onlyOperator() {
        if (msg.sender != operator) revert E.NotExecutor();
        _;
    }

    function committedOf(address asset, address wallet) public view returns (uint256) {
        return reservedOf[asset][wallet] + heldOf[asset][wallet];
    }

    /// @notice Approval: reserve `amount` of `asset` on the wallet that will pay. Reverts if the wallet cannot
    /// cover it on top of its buffer and existing commitments; the backend reports that as a funding deficit.
    function reserve(bytes32 requestId, address asset, address wallet, uint256 amount) external onlyOperator {
        IModuleState s = _state();
        if (requestId == bytes32(0) || amount == 0 || amount > type(uint128).max) revert E.InvalidAmount();
        if (commitments[requestId].wallet != address(0)) revert AlreadyRegistered();
        if (wallet != s.safeT() && !s.isOperational(wallet)) revert E.NotOperationalWallet();
        if (!module.isAssetAllowed(asset)) revert E.AssetNotAllowed();
        if (s.requestPaid(requestId)) revert E.RequestAlreadyPaid();
        if (s.requestCancelled(requestId)) revert E.RequestCancelled();
        uint256 balance = IERC20(asset).balanceOf(wallet);
        uint256 floor = module.bufferOf(asset, wallet) + committedOf(asset, wallet);
        if (balance < floor || amount > balance - floor) revert InsufficientUncommitted();
        commitments[requestId] = Commitment(asset, wallet, uint128(amount), 0);
        reservedOf[asset][wallet] += amount;
        emit Reserved(requestId, asset, wallet, amount);
    }

    /// @notice Execution start: R becomes L for the whole reservation.
    function beginExecution(bytes32 requestId) external onlyOperator {
        Commitment storage c = commitments[requestId];
        uint128 amount = c.reserved;
        if (amount == 0) revert NothingToHold();
        c.reserved = 0;
        c.held += amount;
        reservedOf[c.asset][c.wallet] -= amount;
        heldOf[c.asset][c.wallet] += amount;
        emit HoldStarted(requestId, amount);
    }

    /// @notice Release on a known outcome. A reservation can be cancelled by the operator or the owner. A hold
    /// is released by the operator only once the module shows the request paid or cancelled; otherwise only the
    /// Safe T owner may release it, by declaring the outcome failed. No timeout path exists.
    function release(bytes32 requestId) external {
        IModuleState s = _state();
        bool isOwner = msg.sender == s.safeT();
        if (!isOwner && msg.sender != operator) revert NotOwner();
        Commitment memory c = commitments[requestId];
        if (c.wallet == address(0)) revert NotRegistered();
        if (!isOwner && c.held > 0 && !s.requestPaid(requestId) && !s.requestCancelled(requestId)) {
            revert ReleaseNotAllowed();
        }
        _clear(requestId, c);
        emit Released(requestId, c.reserved, c.held, isOwner);
    }

    function pay(
        ITreasuryPilotModule.PaymentApproval calldata ap,
        bytes calldata approverSig,
        bytes32 stepId,
        uint256 paymentAmount
    ) external onlyOperator {
        module.pay(ap, approverSig, stepId, paymentAmount);
        // The request is paid: its own commitment is consumed before the others are protected.
        Commitment memory c = commitments[ap.requestId];
        if (c.wallet != address(0)) {
            _clear(ap.requestId, c);
            emit Released(ap.requestId, c.reserved, c.held, false);
        }
        _enforce(ap.asset, ap.payingWallet);
    }

    function refill(
        ITreasuryPilotModule.PaymentApproval calldata ap,
        bytes calldata approverSig,
        bytes32 stepId,
        address toWallet,
        uint256 amount
    ) external onlyOperator {
        module.refill(ap, approverSig, stepId, toWallet, amount);
        _enforce(ap.asset, _state().safeT());
    }

    function supply(bytes32 stepId, uint256 amount) external onlyOperator {
        module.supply(stepId, amount);
        _enforceSource();
    }

    function swapForGas(bytes32 stepId, uint256 amountIn, uint256 minOut) external onlyOperator {
        module.swapForGas(stepId, amountIn, minOut);
        _enforceSource();
    }

    function repay(bytes32 planId) external onlyOperator {
        module.repay(planId);
        _enforceSource();
    }

    // These add cash to Safe T, so there is nothing to protect.
    function withdraw(bytes32 stepId, uint256 amount) external onlyOperator {
        module.withdraw(stepId, amount);
    }

    function borrow(bytes32 planId) external onlyOperator {
        module.borrow(planId);
    }

    function _state() internal view returns (IModuleState) {
        return IModuleState(address(module));
    }

    function _clear(bytes32 requestId, Commitment memory c) internal {
        reservedOf[c.asset][c.wallet] -= c.reserved;
        heldOf[c.asset][c.wallet] -= c.held;
        delete commitments[requestId];
    }

    function _enforceSource() internal view {
        IModuleState s = _state();
        _enforce(s.asset(), s.safeT());
    }

    function _enforce(address asset, address wallet) internal view {
        if (IERC20(asset).balanceOf(wallet) < module.bufferOf(asset, wallet) + committedOf(asset, wallet)) {
            revert CommittedFundsBreach();
        }
    }
}
