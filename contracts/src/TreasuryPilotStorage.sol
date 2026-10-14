// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;
import {ITreasuryPilotModule} from "./interfaces/ITreasuryPilotModule.sol";
import {PaymentApprovalHash} from "./libraries/PaymentApprovalHash.sol";

/// @notice Storage belongs to each clone. No field is mutable through a generic call.
abstract contract TreasuryPilotStorage is ITreasuryPilotModule {
    bytes32 public constant PAYMENT_APPROVAL_TYPEHASH = PaymentApprovalHash.TYPEHASH;
    uint8 public constant PAY = 1;
    uint8 public constant REFILL = 2;
    uint8 public constant SWAP_IN = 3;
    uint8 public constant SUPPLY = 4;
    uint8 public constant WITHDRAW = 5;
    address public safeT;
    address public asset;
    address public aavePool;
    address public aToken;
    bool internal _initialized;
    mapping(address => bool) public isOperational;
    address[] internal _operationalList;
    Mandate internal _mandate;
    mapping(address => AssetPolicy) internal _assetPolicies;
    address[] internal _allowedAssetList;
    mapping(address => mapping(address => uint256)) internal _bufferOf;
    mapping(address => mapping(address => uint256)) internal _targetOf;
    mapping(address => bool) public isApprover;
    uint256 public approverCount;
    Status public status;
    mapping(address => Payee) public payees;
    mapping(bytes32 => uint256) public usedOn;
    mapping(bytes32 => bool) public requestPaid;
    mapping(bytes32 => bool) public requestCancelled;
    mapping(bytes32 => bool) public stepUsed;
    mapping(bytes32 => bool) public fingerprintPaid;
    mapping(bytes32 => mapping(address => bool)) public refilledFor;
    mapping(bytes32 => Exception) public exceptions;
    mapping(bytes32 => bytes32) public duplicateAllowedFor;
    mapping(bytes32 => BorrowAuthorization) public borrowAuthorizations;
    mapping(bytes32 => RepayAuthorization) public repayAuthorizations;
    address public swapRouter;
    address public swapTokenOut;
    Limits internal _swapLimits;
}
