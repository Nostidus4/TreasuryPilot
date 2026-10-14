// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;
import {EIP712} from "@openzeppelin/contracts/utils/cryptography/EIP712.sol";
import {SignatureChecker} from "@openzeppelin/contracts/utils/cryptography/SignatureChecker.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {TreasuryPilotStorage} from "./TreasuryPilotStorage.sol";
import {ITreasuryPilotModule} from "./interfaces/ITreasuryPilotModule.sol";
import {TreasuryPilotErrors as E} from "./libraries/TreasuryPilotErrors.sol";
import {PaymentApprovalHash} from "./libraries/PaymentApprovalHash.sol";
import {IAavePool, IAaveToken} from "./interfaces/IAavePool.sol";
import {ISafeModuleWallet} from "./interfaces/ISafeModuleWallet.sol";

/// @notice Owner authority is Safe T itself; human thresholds are enforced by Safe.
abstract contract TreasuryPilotGovernance is TreasuryPilotStorage, EIP712, ReentrancyGuard {
    constructor() EIP712("TreasuryPilot", "1") {
        _initialized = true;
    }

    modifier onlyOwner() {
        if (msg.sender != safeT) revert E.NotOwner();
        _;
    }
    modifier onlyExecutor() {
        if (msg.sender != _mandate.executor) revert E.NotExecutor();
        if (status != Status.Active) revert E.NotActive();
        if (block.timestamp < _mandate.validFrom || block.timestamp > _mandate.expiresAt) revert E.MandateExpired();
        _;
    }

    /// @inheritdoc ITreasuryPilotModule
    function initialize(
        address safeT_,
        address asset_,
        address[] calldata operational_,
        MandateInit calldata m,
        address[] calldata approvers,
        BufferInit[] calldata buffers,
        address aavePool_
    ) external nonReentrant {
        if (_initialized) revert E.AlreadyInitialized();
        _initialized = true;
        if (!_isSafe(safeT_) || asset_.code.length == 0 || operational_.length == 0) revert E.InvalidConfiguration();
        safeT = safeT_;
        asset = asset_;
        for (uint256 i; i < operational_.length; ++i) {
            address wallet = operational_[i];
            if (wallet == safeT_ || isOperational[wallet] || !_isSafe(wallet)) revert E.InvalidConfiguration();
            isOperational[wallet] = true;
            _operationalList.push(wallet);
        }
        _configure(m);
        address[] memory none = new address[](0);
        _setApprovers(approvers, none);
        // Every known wallet must have one explicit buffer entry. Missing entries must not silently mean zero.
        if (buffers.length != operational_.length + 1) revert E.InvalidConfiguration();
        for (uint256 i; i < buffers.length; ++i) {
            for (uint256 j; j < i; ++j) {
                if (buffers[i].wallet == buffers[j].wallet) revert E.InvalidConfiguration();
            }
            _setBuffer(asset_, buffers[i].wallet, buffers[i].buffer, buffers[i].target);
        }
        if (aavePool_ != address(0)) {
            if (aavePool_.code.length == 0) revert E.InvalidConfiguration();
            address reserveToken = IAavePool(aavePool_).getReserveData(asset_).aTokenAddress;
            if (
                reserveToken.code.length == 0 || IAaveToken(reserveToken).UNDERLYING_ASSET_ADDRESS() != asset_
                    || IAaveToken(reserveToken).POOL() != aavePool_
            ) revert E.InvalidConfiguration();
            aavePool = aavePool_;
            aToken = reserveToken;
        } else if (m.supply.perRequest != 0 || m.supply.daily != 0) {
            revert E.InvalidConfiguration();
        }
    }

    /// @inheritdoc ITreasuryPilotModule
    function configureMandate(MandateInit calldata m) external onlyOwner nonReentrant {
        if (aavePool == address(0) && (m.supply.perRequest != 0 || m.supply.daily != 0)) {
            revert E.InvalidConfiguration();
        }
        _configure(m);
    }

    function _configure(MandateInit memory m) internal {
        if (m.expiresAt <= m.validFrom) revert E.InvalidMandate("expiresAt");
        if (m.executor == address(0)) revert E.InvalidMandate("executor");
        if (m.payeeCoolingSeconds == 0) revert E.InvalidMandate("payeeCoolingSeconds");
        if (m.pay.perRequest > m.pay.daily) revert E.InvalidMandate("pay");
        if (m.refill.perRequest > m.refill.daily) revert E.InvalidMandate("refill");
        if (m.supply.perRequest > m.supply.daily) revert E.InvalidMandate("supply");
        if (m.approvalMaxAge == 0) revert E.InvalidMandate("approvalMaxAge");
        // A new mandate version invalidates secondary-asset policies; the owner must re-enable them under it.
        for (uint256 i = _allowedAssetList.length; i > 0; --i) {
            if (_allowedAssetList[i - 1] != asset) _clearAsset(_allowedAssetList[i - 1]);
        }
        if (!_assetPolicies[asset].enabled) _allowedAssetList.push(asset);
        _assetPolicies[asset] = AssetPolicy(true, m.pay, m.refill);
        _mandate = Mandate(
            _mandate.version + 1,
            m.validFrom,
            m.expiresAt,
            m.payeeCoolingSeconds,
            m.executor,
            m.guardian,
            m.pay,
            m.refill,
            m.approvalMaxAge,
            m.supply
        );
        emit MandateConfigured(_mandate.version, m.expiresAt);
    }

    /// @inheritdoc ITreasuryPilotModule
    function setApprovers(address[] calldata add, address[] calldata remove) external onlyOwner nonReentrant {
        _setApprovers(add, remove);
    }

    function _setApprovers(address[] memory add, address[] memory remove) internal {
        for (uint256 i; i < add.length; ++i) {
            if (add[i] == address(0)) revert E.InvalidConfiguration();
            if (!isApprover[add[i]]) {
                isApprover[add[i]] = true;
                ++approverCount;
            }
        }
        for (uint256 i; i < remove.length; ++i) {
            if (isApprover[remove[i]]) {
                isApprover[remove[i]] = false;
                --approverCount;
            }
        }
        if (approverCount == 0) revert E.NoApprovers();
        emit ApproversChanged(add, remove);
    }

    /// @inheritdoc ITreasuryPilotModule
    function setBuffer(address wallet, uint256 buffer, uint256 target) external onlyOwner nonReentrant {
        _setBuffer(asset, wallet, buffer, target);
    }

    /// @inheritdoc ITreasuryPilotModule
    function setBuffer(address asset_, address wallet, uint256 buffer, uint256 target)
        external
        onlyOwner
        nonReentrant
    {
        _setBuffer(asset_, wallet, buffer, target);
    }

    /// @inheritdoc ITreasuryPilotModule
    function setAssetPolicy(address asset_, bool enabled, Limits calldata pay, Limits calldata refill)
        external
        onlyOwner
        nonReentrant
    {
        if (
            asset_ == address(0) || asset_.code.length == 0 || asset_ == asset
                || pay.perRequest > pay.daily || refill.perRequest > refill.daily
        ) revert E.InvalidConfiguration();
        if (!enabled) {
            _clearAsset(asset_);
            return;
        }
        AssetPolicy storage policy = _assetPolicies[asset_];
        if (!policy.enabled) {
            // A floor must be positive and every operational wallet needs a refill target, not just a touched flag.
            if (!_assetBufferConfigured[asset_][safeT] || _bufferOf[asset_][safeT] == 0) {
                revert E.AssetBufferNotConfigured();
            }
            for (uint256 i; i < _operationalList.length; ++i) {
                address wallet = _operationalList[i];
                if (!_assetBufferConfigured[asset_][wallet] || _targetOf[asset_][wallet] == 0) {
                    revert E.AssetBufferNotConfigured();
                }
            }
            _allowedAssetList.push(asset_);
        }
        policy.enabled = true;
        policy.pay = pay;
        policy.refill = refill;
        emit AssetPolicySet(asset_, true, pay.perRequest, pay.daily, refill.perRequest, refill.daily);
    }

    /// @dev Disabling drops the policy and its buffers so re-enabling must reconfigure them explicitly.
    function _clearAsset(address asset_) internal {
        if (_assetPolicies[asset_].enabled) {
            for (uint256 i; i < _allowedAssetList.length; ++i) {
                if (_allowedAssetList[i] == asset_) {
                    _allowedAssetList[i] = _allowedAssetList[_allowedAssetList.length - 1];
                    _allowedAssetList.pop();
                    break;
                }
            }
            emit AssetPolicySet(asset_, false, 0, 0, 0, 0);
        }
        delete _assetPolicies[asset_];
        _clearBuffer(asset_, safeT);
        for (uint256 i; i < _operationalList.length; ++i) {
            _clearBuffer(asset_, _operationalList[i]);
        }
    }

    function _clearBuffer(address asset_, address wallet) internal {
        delete _bufferOf[asset_][wallet];
        delete _targetOf[asset_][wallet];
        delete _assetBufferConfigured[asset_][wallet];
    }

    function _setBuffer(address asset_, address wallet, uint256 buffer, uint256 target) internal {
        if (asset_ == address(0) || asset_.code.length == 0) revert E.AssetNotAllowed();
        if (wallet != safeT && !isOperational[wallet]) revert E.UnknownWallet();
        if (isOperational[wallet] && target < buffer) revert E.TargetBelowBuffer();
        _bufferOf[asset_][wallet] = buffer;
        _targetOf[asset_][wallet] = target;
        _assetBufferConfigured[asset_][wallet] = true;
        if (asset_ == asset) emit BufferSet(wallet, buffer, target);
        emit AssetBufferSet(asset_, wallet, buffer, target);
    }

    function isAssetAllowed(address asset_) public view returns (bool) {
        return asset_ != address(0) && _assetPolicies[asset_].enabled;
    }

    function allowedAssets() external view returns (address[] memory) {
        return _allowedAssetList;
    }

    function assetPolicyOf(address asset_) external view returns (AssetPolicy memory) {
        return _assetPolicies[asset_];
    }

    function bufferOf(address wallet) public view returns (uint256) {
        return _bufferOf[asset][wallet];
    }

    function bufferOf(address asset_, address wallet) public view returns (uint256) {
        return _bufferOf[asset_][wallet];
    }

    function targetOf(address wallet) public view returns (uint256) {
        return _targetOf[asset][wallet];
    }

    function targetOf(address asset_, address wallet) public view returns (uint256) {
        return _targetOf[asset_][wallet];
    }

    /// @inheritdoc ITreasuryPilotModule
    function addPayee(address payee) external onlyOwner nonReentrant {
        if (payee == address(0) || payee == safeT || isOperational[payee]) revert E.InvalidPayee();
        uint64 activeFrom = uint64(block.timestamp + _mandate.payeeCoolingSeconds);
        payees[payee] = Payee(activeFrom, true);
        emit PayeeAdded(payee, activeFrom);
    }

    /// @inheritdoc ITreasuryPilotModule
    function deactivatePayee(address payee) external onlyOwner nonReentrant {
        if (payees[payee].activeFrom == 0) revert E.UnknownPayee();
        payees[payee].active = false;
        emit PayeeDeactivated(payee);
    }

    /// @inheritdoc ITreasuryPilotModule
    function grantException(bytes32 requestId, uint128 amount, address payee, uint64 expiry)
        external
        onlyOwner
        nonReentrant
    {
        if (requestPaid[requestId]) revert E.AlreadyPaid();
        if (expiry < block.timestamp) revert E.ExpiryInPast();
        if (requestId == bytes32(0) || amount == 0 || payee == address(0)) revert E.InvalidConfiguration();
        exceptions[requestId] = Exception(amount, expiry, _mandate.version, payee, false);
        emit ExceptionGranted(requestId, amount, payee, expiry, _mandate.version);
    }

    /// @inheritdoc ITreasuryPilotModule
    function revokeException(bytes32 requestId) external onlyOwner nonReentrant {
        delete exceptions[requestId];
        emit ExceptionRevoked(requestId);
    }

    /// @inheritdoc ITreasuryPilotModule
    function allowDuplicate(bytes32 fingerprint, bytes32 requestId) external onlyOwner nonReentrant {
        if (requestId == bytes32(0) || fingerprint == bytes32(0)) revert E.InvalidConfiguration();
        if (requestPaid[requestId]) revert E.AlreadyPaid();
        duplicateAllowedFor[fingerprint] = requestId;
        emit DuplicateAllowed(fingerprint, requestId);
    }

    /// @inheritdoc ITreasuryPilotModule
    function pause() external nonReentrant {
        if (msg.sender != safeT && msg.sender != _mandate.guardian) revert E.NotGuardianOrOwner();
        if (status == Status.Revoked) revert E.Revoked();
        if (status != Status.Paused) {
            status = Status.Paused;
            emit Paused(msg.sender);
        }
    }

    /// @inheritdoc ITreasuryPilotModule
    function resume() external onlyOwner nonReentrant {
        if (status != Status.Paused) revert E.NotPaused();
        status = Status.Active;
        emit Resumed();
    }

    /// @inheritdoc ITreasuryPilotModule
    function revoke() external onlyOwner nonReentrant {
        if (status == Status.Revoked) revert E.AlreadyRevoked();
        status = Status.Revoked;
        emit Revoked();
    }

    /// @inheritdoc ITreasuryPilotModule
    function cancelRequest(bytes32 requestId) external nonReentrant {
        if (msg.sender != safeT && !isApprover[msg.sender]) revert E.NotOwnerOrApprover();
        if (requestPaid[requestId]) revert E.AlreadyPaid();
        if (!requestCancelled[requestId]) {
            requestCancelled[requestId] = true;
            emit RequestCancelled(requestId, msg.sender);
        }
    }

    /// @inheritdoc ITreasuryPilotModule
    function mandate() external view returns (Mandate memory) {
        return _mandate;
    }

    /// @inheritdoc ITreasuryPilotModule
    function operationalList() external view returns (address[] memory) {
        return _operationalList;
    }

    /// @inheritdoc ITreasuryPilotModule
    function payeeStatus(address payee) external view returns (PayeeState state, uint64 activeFrom) {
        Payee memory p = payees[payee];
        if (p.activeFrom == 0) state = PayeeState.Unknown;
        else if (!p.active) state = PayeeState.Deactivated;
        else if (block.timestamp < p.activeFrom) state = PayeeState.Cooling;
        else state = PayeeState.Active;
        return (state, p.activeFrom);
    }

    /// @inheritdoc ITreasuryPilotModule
    function domainSeparator() external view returns (bytes32) {
        return _domainSeparatorV4();
    }

    /// @inheritdoc ITreasuryPilotModule
    function hashApproval(PaymentApproval calldata ap) public view returns (bytes32) {
        return _hashTypedDataV4(PaymentApprovalHash.structHash(ap));
    }

    /// @inheritdoc ITreasuryPilotModule
    function verifyApproval(PaymentApproval calldata ap, bytes calldata approverSig)
        public
        view
        returns (address signer)
    {
        if (
            ap.treasury != address(this) || !isAssetAllowed(ap.asset) || ap.requestId == bytes32(0)
                || ap.fingerprint == bytes32(0) || ap.amount == 0
        ) revert E.ApprovalInvalid();
        if (block.timestamp > ap.expiry) revert E.ApprovalExpired();
        if (ap.earlyAmount > ap.amount) revert E.WrongPaymentOption();
        // Verify canonical ABI framing before decoding untrusted input, including arbitrary ERC-1271 lengths.
        if (approverSig.length < 96) revert E.ApprovalInvalid();
        uint256 identity;
        uint256 offset;
        uint256 sigLength;
        assembly ("memory-safe") {
            identity := calldataload(approverSig.offset)
            offset := calldataload(add(approverSig.offset, 32))
            sigLength := calldataload(add(approverSig.offset, 64))
        }
        if (
            identity > type(uint160).max || offset != 64 || sigLength > approverSig.length - 96
                || approverSig.length - 96 - sigLength >= 32
        ) revert E.ApprovalInvalid();
        signer = address(uint160(identity));
        if (!isApprover[signer]) revert E.NotApprover();
        if (!SignatureChecker.isValidSignatureNow(signer, hashApproval(ap), approverSig[96:96 + sigLength])) {
            revert E.ApprovalInvalid();
        }
    }

    function _isSafe(address wallet) internal view returns (bool) {
        if (wallet.code.length == 0) return false;
        try ISafeModuleWallet(wallet).getThreshold() returns (uint256 threshold) {
            if (threshold == 0) return false;
            try ISafeModuleWallet(wallet).getOwners() returns (address[] memory owners) {
                return owners.length >= threshold;
            } catch {
                return false;
            }
        } catch {
            return false;
        }
    }
}
