// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {Enum} from "@safe-global/safe-contracts/contracts/common/Enum.sol";
import {ITreasuryPilotModule} from "./interfaces/ITreasuryPilotModule.sol";
import {ISafeModuleWallet} from "./interfaces/ISafeModuleWallet.sol";
import {IAavePool, IAaveToken} from "./interfaces/IAavePool.sol";
import {TreasuryPilotGovernance} from "./TreasuryPilotGovernance.sol";
import {TreasuryPilotErrors as E} from "./libraries/TreasuryPilotErrors.sol";

interface ITestRouter {
    function tokenIn() external view returns (address);
    function tokenOut() external view returns (address);
    function swap(uint256 amountIn, uint256 minOut, address recipient) external returns (uint256);
}

/// @notice Executes fixed ERC20 and Aave calls through Safes, within signed and owner-set rules.
contract TreasuryPilotModule is TreasuryPilotGovernance {
    /// @inheritdoc ITreasuryPilotModule
    function pay(PaymentApproval calldata ap, bytes calldata approverSig, bytes32 stepId, uint256 paymentAmount)
        external
        onlyExecutor
        nonReentrant
    {
        verifyApproval(ap, approverSig);
        if (!isOperational[ap.payingWallet]) revert E.NotOperationalWallet();
        _requireActivePayee(ap.payee);
        _requireUnpaid(ap.requestId);
        _requireUnusedStep(stepId);
        if (fingerprintPaid[ap.fingerprint]) {
            if (duplicateAllowedFor[ap.fingerprint] != ap.requestId) revert E.DuplicateFingerprint();
            delete duplicateAllowedFor[ap.fingerprint];
        }
        bool early = ap.earlyAmount > 0 && block.timestamp <= ap.earlyPayBy;
        uint256 approvedAmount = early ? ap.earlyAmount : ap.amount;
        if (paymentAmount == 0) revert E.InvalidAmount();
        // Only an owner-signed fiat approval may pay below the signed option; everything else pays it exactly.
        if (ap.isFiat ? paymentAmount > approvedAmount : paymentAmount != approvedAmount) {
            revert E.WrongPaymentOption();
        }
        bool usedException = false;
        Limits storage limits = _assetPolicies[ap.asset].pay;
        if (paymentAmount > limits.perRequest) {
            Exception storage ex = exceptions[ap.requestId];
            if (ex.amount == 0) revert E.OverPerRequestLimit();
            if (
                ex.amount != approvedAmount || ex.payee != ap.payee || ex.used || block.timestamp > ex.expiry
                    || ex.mandateVersion != _mandate.version
            ) revert E.ExceptionInvalid();
            ex.used = true;
            usedException = true;
        }
        uint256 day = block.timestamp / 1 days;
        bytes32 key = _counterKey(PAY, ap.asset, day);
        if (_exceedsDaily(usedOn[key], paymentAmount, limits.daily)) revert E.OverDailyLimit();
        _requireFloor(ap.asset, ap.payingWallet, paymentAmount, false);
        requestPaid[ap.requestId] = true;
        stepUsed[stepId] = true;
        fingerprintPaid[ap.fingerprint] = true;
        usedOn[key] += paymentAmount;
        _transfer(ap.asset, ap.payingWallet, ap.payee, paymentAmount);
        if (_balance(ap.asset, ap.payingWallet) < bufferOf(ap.asset, ap.payingWallet)) {
            revert E.BufferBreach();
        }
        emit PaymentExecuted(
            ap.requestId, stepId, ap.fingerprint, ap.payingWallet, ap.payee, paymentAmount, day, usedException, early
        );
    }

    /// @inheritdoc ITreasuryPilotModule
    function refill(
        PaymentApproval calldata ap,
        bytes calldata approverSig,
        bytes32 stepId,
        address fromWallet,
        address toWallet,
        uint256 amount
    ) external onlyExecutor nonReentrant {
        if (fromWallet != safeT && !_refillPath[fromWallet][toWallet]) {
            revert E.RefillPathNotAllowed();
        }
        verifyApproval(ap, approverSig);
        _requireUnpaid(ap.requestId);
        _requireUnusedStep(stepId);
        if (toWallet != ap.payingWallet || !isOperational[toWallet]) revert E.WrongRefillTarget();
        if (refilledFor[ap.requestId][toWallet]) revert E.AlreadyRefilledForRequest();
        if (amount == 0) revert E.InvalidAmount();
        Limits storage limits = _assetPolicies[ap.asset].refill;
        if (amount > limits.perRequest) revert E.OverRefillPerRequest();
        uint256 day = block.timestamp / 1 days;
        bytes32 key = _counterKey(REFILL, ap.asset, day);
        if (_exceedsDaily(usedOn[key], amount, limits.daily)) revert E.OverRefillDaily();
        _requireFloor(ap.asset, fromWallet, amount, true);
        uint256 beforeTo = _balance(ap.asset, toWallet);
        // ap.amount is a uint256: an overflowing sum reverts (checked arithmetic), it never wraps.
        if (beforeTo + amount > ap.amount + targetOf(ap.asset, toWallet)) revert E.RefillExceedsNeed();
        stepUsed[stepId] = true;
        refilledFor[ap.requestId][toWallet] = true;
        usedOn[key] += amount;
        _transfer(ap.asset, fromWallet, toWallet, amount);
        emit RefillExecuted(ap.requestId, stepId, toWallet, amount, day);
    }

    /// @inheritdoc ITreasuryPilotModule
    function supply(bytes32 stepId, uint256 amount) external onlyExecutor nonReentrant {
        _requirePool();
        _requireUnusedStep(stepId);
        if (amount == 0) revert E.InvalidAmount();
        if (amount > _mandate.supply.perRequest) revert E.OverSupplyPerTx();
        uint256 day = block.timestamp / 1 days;
        bytes32 key = _counterKey(SUPPLY, asset, day);
        if (_exceedsDaily(usedOn[key], amount, _mandate.supply.daily)) revert E.OverSupplyDaily();
        uint256 beforeCash = _balance(safeT);
        if (beforeCash < amount || beforeCash - amount < bufferOf(safeT)) revert E.SupplyFloorBreach();
        uint256 scaledBefore = IAaveToken(aToken).scaledBalanceOf(safeT);
        uint256 normalizedIncome = IAavePool(aavePool).getReserveNormalizedIncome(asset);
        if (normalizedIncome == 0) revert E.BalanceDeltaMismatch();
        // Support Aave's half-up and floor mint rounding. Reject any deficit below
        // the exact floor, any surplus above half-up, and zero minted shares.
        uint256 floorScaled = amount * 1e27 / normalizedIncome;
        uint256 expectedScaled = (amount * 1e27 + normalizedIncome / 2) / normalizedIncome;
        stepUsed[stepId] = true;
        usedOn[key] += amount;
        _approve(aavePool, amount);
        _safeCall(safeT, aavePool, abi.encodeCall(IAavePool.supply, (asset, amount, safeT, 0)));
        _clearAllowance(aavePool);
        uint256 afterCash = _balance(safeT);
        uint256 scaledAfter = IAaveToken(aToken).scaledBalanceOf(safeT);
        if (
            afterCash > beforeCash || beforeCash - afterCash != amount || scaledAfter <= scaledBefore
                || scaledAfter - scaledBefore < floorScaled || scaledAfter - scaledBefore > expectedScaled
        ) revert E.BalanceDeltaMismatch();
        if (afterCash < bufferOf(safeT)) revert E.SupplyFloorBreach();
        emit Supplied(stepId, amount, day);
    }

    /// @inheritdoc ITreasuryPilotModule
    function withdraw(bytes32 stepId, uint256 amount) external onlyExecutor nonReentrant {
        _requirePool();
        _requireUnusedStep(stepId);
        if (amount == 0) revert E.InvalidAmount();
        if (amount > IERC20(aToken).balanceOf(safeT)) revert E.InsufficientAToken();
        uint256 beforeCash = _balance(safeT);
        stepUsed[stepId] = true;
        bytes memory result = _safeCall(safeT, aavePool, abi.encodeCall(IAavePool.withdraw, (asset, amount, safeT)));
        if (result.length != 32 || abi.decode(result, (uint256)) != amount) revert E.BalanceDeltaMismatch();
        uint256 afterCash = _balance(safeT);
        if (afterCash < beforeCash || afterCash - beforeCash != amount) revert E.BalanceDeltaMismatch();
        if (IERC20(asset).allowance(safeT, aavePool) != 0) revert E.AllowanceNotCleared();
        emit Withdrawn(stepId, amount, block.timestamp / 1 days);
    }

    /// @inheritdoc ITreasuryPilotModule
    function authorizeBorrow(bytes32 planId, uint256 amount, uint64 expiry, uint256 minHealthFactor, uint256 maxRateRay)
        external
        onlyOwner
        nonReentrant
    {
        _requirePool();
        if (planId == bytes32(0) || amount == 0 || minHealthFactor < 1e18) revert E.InvalidConfiguration();
        if (expiry < block.timestamp) revert E.ExpiryInPast();
        // A plan hash cannot be re-authorized after consumption. A changed plan requires a new hash.
        if (borrowAuthorizations[planId].used) revert E.AuthorizationAlreadyUsed();
        borrowAuthorizations[planId] = BorrowAuthorization(amount, expiry, minHealthFactor, maxRateRay, false);
        emit BorrowAuthorized(planId, amount, expiry, minHealthFactor, maxRateRay);
    }

    /// @inheritdoc ITreasuryPilotModule
    function authorizeRepay(bytes32 planId, uint256 amount, uint64 expiry) external onlyOwner nonReentrant {
        _requirePool();
        if (planId == bytes32(0) || amount == 0) revert E.InvalidConfiguration();
        if (expiry < block.timestamp) revert E.ExpiryInPast();
        if (repayAuthorizations[planId].used) revert E.AuthorizationAlreadyUsed();
        repayAuthorizations[planId] = RepayAuthorization(amount, expiry, false);
        emit RepayAuthorized(planId, amount, expiry);
    }

    /// @inheritdoc ITreasuryPilotModule
    function borrow(bytes32 planId) external onlyExecutor nonReentrant {
        _requirePool();
        BorrowAuthorization storage auth = borrowAuthorizations[planId];
        if (auth.amount == 0 || auth.used) revert E.BorrowNotAuthorized();
        if (block.timestamp > auth.expiry) revert E.AuthorizationExpired();
        _requireBorrowGuards(auth);
        uint256 beforeCash = _balance(safeT);
        auth.used = true;
        _safeCall(safeT, aavePool, abi.encodeCall(IAavePool.borrow, (asset, auth.amount, 2, 0, safeT)));
        uint256 afterCash = _balance(safeT);
        if (afterCash < beforeCash || afterCash - beforeCash != auth.amount) revert E.BalanceDeltaMismatch();
        _requireBorrowGuards(auth);
        emit BorrowExecuted(planId, auth.amount);
    }

    /// @inheritdoc ITreasuryPilotModule
    function repay(bytes32 planId) external onlyExecutor nonReentrant {
        _requirePool();
        RepayAuthorization storage auth = repayAuthorizations[planId];
        if (auth.amount == 0 || auth.used) revert E.RepayNotAuthorized();
        if (block.timestamp > auth.expiry) revert E.AuthorizationExpired();
        _requireFloor(safeT, auth.amount, true);
        uint256 beforeCash = _balance(safeT);
        uint256 beforeHF = _healthFactor();
        auth.used = true;
        _approve(aavePool, auth.amount);
        bytes memory result =
            _safeCall(safeT, aavePool, abi.encodeCall(IAavePool.repay, (asset, auth.amount, 2, safeT)));
        _clearAllowance(aavePool);
        if (result.length != 32) revert E.BalanceDeltaMismatch();
        uint256 paid = abi.decode(result, (uint256));
        uint256 afterCash = _balance(safeT);
        if (paid == 0 || paid > auth.amount || afterCash > beforeCash || beforeCash - afterCash != paid) {
            revert E.BalanceDeltaMismatch();
        }
        if (afterCash < bufferOf(safeT)) revert E.SourceBufferBreach();
        if (_healthFactor() < beforeHF) revert E.HealthFactorTooLow();
        emit Repaid(planId, paid);
    }

    /// @inheritdoc ITreasuryPilotModule
    function configureSwap(address router, address tokenOut, Limits calldata limits) external onlyOwner nonReentrant {
        if (
            router.code.length == 0 || tokenOut.code.length == 0 || tokenOut == asset
                || limits.perRequest > limits.daily || ITestRouter(router).tokenIn() != asset
                || ITestRouter(router).tokenOut() != tokenOut
        ) revert E.RouterNotAllowed();
        swapRouter = router;
        swapTokenOut = tokenOut;
        _swapLimits = limits;
        emit SwapConfigured(router, tokenOut, limits.perRequest, limits.daily);
    }

    /// @inheritdoc ITreasuryPilotModule
    function swapForGas(bytes32 stepId, uint256 amountIn, uint256 minOut) external onlyExecutor nonReentrant {
        if (swapRouter == address(0)) revert E.RouterNotAllowed();
        _requireUnusedStep(stepId);
        if (amountIn == 0 || minOut == 0) revert E.InvalidAmount();
        if (amountIn > _swapLimits.perRequest) revert E.OverSwapPerTx();
        uint256 day = block.timestamp / 1 days;
        bytes32 key = _counterKey(SWAP_IN, asset, day);
        if (_exceedsDaily(usedOn[key], amountIn, _swapLimits.daily)) revert E.OverSwapDaily();
        _requireFloor(safeT, amountIn, true);
        uint256 beforeCash = _balance(safeT);
        uint256 beforeOut = IERC20(swapTokenOut).balanceOf(safeT);
        stepUsed[stepId] = true;
        usedOn[key] += amountIn;
        _approve(swapRouter, amountIn);
        _safeCall(safeT, swapRouter, abi.encodeCall(ITestRouter.swap, (amountIn, minOut, safeT)));
        _clearAllowance(swapRouter);
        uint256 afterOut = IERC20(swapTokenOut).balanceOf(safeT);
        uint256 afterCash = _balance(safeT);
        if (afterCash > beforeCash || beforeCash - afterCash != amountIn || afterOut < beforeOut) {
            revert E.BalanceDeltaMismatch();
        }
        uint256 amountOut = afterOut - beforeOut;
        if (amountOut < minOut) revert E.InsufficientOutput();
        if (afterCash < bufferOf(safeT)) revert E.SourceBufferBreach();
        emit SwappedForGas(stepId, amountIn, amountOut, day);
    }

    /// @inheritdoc ITreasuryPilotModule
    function usedToday(uint8 action, address asset_) public view returns (uint256) {
        return usedOn[_counterKey(action, asset_, block.timestamp / 1 days)];
    }

    /// @inheritdoc ITreasuryPilotModule
    function remainingToday(uint8 action, address asset_) public view returns (uint256) {
        uint256 cap = 0;
        if (!isAssetAllowed(asset_)) return 0;
        if (action == PAY) cap = _assetPolicies[asset_].pay.daily;
        else if (action == REFILL) cap = _assetPolicies[asset_].refill.daily;
        else if (action == SUPPLY && asset_ == asset) cap = _mandate.supply.daily;
        else if (action == SWAP_IN && asset_ == asset) cap = _swapLimits.daily;
        uint256 used = usedToday(action, asset_);
        return used >= cap ? 0 : cap - used;
    }

    function _counterKey(uint8 action, address asset_, uint256 day) internal pure returns (bytes32) {
        return keccak256(abi.encode(action, asset_, day));
    }

    function _exceedsDaily(uint256 used, uint256 amount, uint256 limit) internal pure returns (bool) {
        return used > limit || amount > limit - used;
    }

    function _requireActivePayee(address payee) internal view {
        Payee memory p = payees[payee];
        if (!p.active) revert E.PayeeUnknown();
        if (block.timestamp < p.activeFrom) revert E.PayeeCooling();
    }

    function _requireUnpaid(bytes32 requestId) internal view {
        if (requestPaid[requestId]) revert E.RequestAlreadyPaid();
        if (requestCancelled[requestId]) revert E.RequestCancelled();
    }

    function _requireUnusedStep(bytes32 stepId) internal view {
        if (stepId == bytes32(0)) revert E.InvalidConfiguration();
        if (stepUsed[stepId]) revert E.StepAlreadyExecuted();
    }

    function _requireFloor(address wallet, uint256 amount, bool source) internal view {
        _requireFloor(asset, wallet, amount, source);
    }

    function _requireFloor(address asset_, address wallet, uint256 amount, bool source) internal view {
        uint256 balance = _balance(asset_, wallet);
        if (balance < amount || balance - amount < bufferOf(asset_, wallet)) {
            if (source) revert E.SourceBufferBreach();
            revert E.BufferBreach();
        }
    }

    function _balance(address wallet) internal view returns (uint256) {
        return _balance(asset, wallet);
    }

    function _balance(address asset_, address wallet) internal view returns (uint256) {
        return IERC20(asset_).balanceOf(wallet);
    }

    function _transfer(address asset_, address from, address to, uint256 amount) internal {
        uint256 beforeFrom = _balance(asset_, from);
        uint256 beforeTo = _balance(asset_, to);
        _safeTokenCall(asset_, from, abi.encodeCall(IERC20.transfer, (to, amount)));
        uint256 afterFrom = _balance(asset_, from);
        uint256 afterTo = _balance(asset_, to);
        if (
            afterFrom > beforeFrom || beforeFrom - afterFrom != amount || afterTo < beforeTo
                || afterTo - beforeTo != amount
        ) revert E.BalanceDeltaMismatch();
    }

    function _safeCall(address wallet, address target, bytes memory data) internal returns (bytes memory result) {
        try ISafeModuleWallet(wallet)
            .execTransactionFromModuleReturnData(target, 0, data, Enum.Operation.Call) returns (
            bool success, bytes memory returnData
        ) {
            if (!success) revert E.TransferFailed();
            return returnData;
        } catch {
            revert E.TransferFailed();
        }
    }

    function _safeTokenCall(address wallet, bytes memory data) internal {
        _safeTokenCall(asset, wallet, data);
    }

    function _safeTokenCall(address asset_, address wallet, bytes memory data) internal {
        bytes memory result = _safeCall(wallet, asset_, data);
        if (result.length == 0) return;
        if (result.length != 32) revert E.TransferFailed();
        uint256 returnValue;
        assembly ("memory-safe") { returnValue := mload(add(result, 32)) }
        if (returnValue != 1) revert E.TransferFailed();
    }

    function _approve(address spender, uint256 amount) internal {
        _safeTokenCall(safeT, abi.encodeCall(IERC20.approve, (spender, 0)));
        _safeTokenCall(safeT, abi.encodeCall(IERC20.approve, (spender, amount)));
    }

    function _clearAllowance(address spender) internal {
        _safeTokenCall(safeT, abi.encodeCall(IERC20.approve, (spender, 0)));
        if (IERC20(asset).allowance(safeT, spender) != 0) revert E.AllowanceNotCleared();
    }

    function _requirePool() internal view {
        if (aavePool == address(0)) revert E.InvalidConfiguration();
    }

    /// @dev Health factor and borrow rate must hold both before and after the borrow.
    function _requireBorrowGuards(BorrowAuthorization storage auth) internal view {
        if (_healthFactor() < auth.minHealthFactor) revert E.HealthFactorTooLow();
        if (IAavePool(aavePool).getReserveData(asset).currentVariableBorrowRate > auth.maxRateRay) {
            revert E.BorrowRateTooHigh();
        }
    }

    function _healthFactor() internal view returns (uint256 healthFactor) {
        (,,,,, healthFactor) = IAavePool(aavePool).getUserAccountData(safeT);
    }
}
