// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;
import {TreasuryFixture} from "../helpers/TreasuryFixture.sol";
import {Vm} from "../helpers/Vm.sol";
import {TreasuryPilotModule} from "../../src/TreasuryPilotModule.sol";
import {ITreasuryPilotModule as I} from "../../src/interfaces/ITreasuryPilotModule.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";

/// @notice Independent ghost accounting records preconditions at execution time.
/// Owner lowering a cap later does not retroactively invalidate yesterday's payments.
contract TreasuryHandler {
    Vm internal constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));
    TreasuryPilotModule public immutable module;
    IERC20 public immutable token;
    address public immutable executor;
    address public immutable owner;
    address public immutable vendor;
    address public immutable approver;
    address public immutable op1;
    address public immutable op2;
    uint256 public violations;
    bytes32[] internal borrowPlanIds;
    uint256 internal borrowNonce;
    uint256 public successes;
    uint256 public replayAttempts;
    uint256 public replayRejections;
    uint256 public borrowSuccesses;
    uint256 public borrowAttempts;
    bytes32[] internal successfulSteps;
    mapping(bytes32 => I.BorrowAuthorization) internal expectedBorrowGrants;
    mapping(bytes32 => bool) internal borrowedPlans;
    mapping(bytes32 => uint256) public expectedCounters;
    mapping(bytes32 => uint256) public paymentCount;
    mapping(bytes32 => uint256) public stepCount;
    mapping(bytes32 => uint256) public fingerprintCount;
    bytes32[] internal observedKeys;
    mapping(bytes32 => bool) internal knownKey;
    uint256 internal nonce;

    constructor(TreasuryPilotModule module_, address vendor_, address op1_, address op2_) {
        module = module_;
        token = IERC20(module_.asset());
        executor = module_.mandate().executor;
        owner = module_.safeT();
        vendor = vendor_;
        op1 = op1_;
        op2 = op2_;
        approver = vm.addr(7);
    }

    function _flag(uint256 id, bool failed) internal {
        if (failed) violations |= uint256(1) << id;
    }

    function _active() internal view returns (bool) {
        I.Mandate memory m = module.mandate();
        return module.status() == I.Status.Active && block.timestamp >= m.validFrom && block.timestamp <= m.expiresAt;
    }

    function _signature(I.PaymentApproval memory ap) internal view returns (bytes memory) {
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(7, module.hashApproval(ap));
        return abi.encode(approver, abi.encodePacked(r, s, v));
    }

    function _approval(uint256 seed) internal view returns (I.PaymentApproval memory ap) {
        ap = I.PaymentApproval(
            bytes32(seed % 64 + 1),
            keccak256("invoice"),
            bytes32(seed % 16 + 1),
            address(module),
            seed % 2 == 0 ? op1 : op2,
            address(token),
            vendor,
            seed % 3000e6 + 1,
            seed % 3 == 0 ? seed % 1000e6 + 1 : 0,
            uint64(block.timestamp),
            uint64(block.timestamp + 1 days),
            keccak256("terms"),
            uint64(block.timestamp + 14 days)
        );
    }

    function _step() internal returns (bytes32) {
        return keccak256(abi.encode("handler", ++nonce));
    }

    function _observe(uint8 action, uint256 amount) internal {
        bytes32 key = keccak256(abi.encode(action, module.asset(), block.timestamp / 1 days));
        if (!knownKey[key]) {
            knownKey[key] = true;
            observedKeys.push(key);
        }
        expectedCounters[key] += amount;
        _flag(8, module.usedOn(key) != expectedCounters[key]);
    }

    function countersMatch() external view returns (bool) {
        for (uint256 i; i < observedKeys.length; ++i) {
            if (module.usedOn(observedKeys[i]) != expectedCounters[observedKeys[i]]) return false;
        }
        return true;
    }

    function pay(uint256 seed) external {
        I.PaymentApproval memory ap = _approval(seed);
        bytes memory sig = _signature(ap);
        bool proofValid = true;
        if (seed % 5 == 0) {
            ++ap.amount;
            proofValid = false;
        }
        bytes32 step = _step();
        uint256 amount = ap.earlyAmount > 0 && block.timestamp <= ap.earlyPayBy ? ap.earlyAmount : ap.amount;
        I.Mandate memory m = module.mandate();
        bool active = _active();
        bool cancelled = module.requestCancelled(ap.requestId);
        bool duplicateAllowed = module.duplicateAllowedFor(ap.fingerprint) == ap.requestId;
        (uint64 activeFrom, bool payeeActive) = module.payees(vendor);
        uint256 beforeUsed = module.usedToday(module.PAY());
        uint256 beforeRecipient = token.balanceOf(vendor);
        (uint128 exAmount, uint64 exExpiry, uint64 exVersion, address exPayee, bool exUsed) =
            module.exceptions(ap.requestId);
        bool exceptionValid =
            exAmount == amount && block.timestamp <= exExpiry && exVersion == m.version && exPayee == vendor && !exUsed;
        vm.prank(executor);
        try module.pay(ap, sig, step) {
            ++successes;
            _flag(1, !proofValid || !module.isApprover(approver)); // BR-001/003/004
            _flag(2, !payeeActive || block.timestamp < activeFrom); // BR-013/017
            _flag(3, beforeUsed > m.pay.daily || amount > m.pay.daily - beforeUsed); // BR-022
            _flag(4, token.balanceOf(ap.payingWallet) < module.bufferOf(ap.payingWallet)); // BR-030
            _flag(
                5,
                ++paymentCount[ap.requestId] > 1 || ++stepCount[step] > 1
                    || (++fingerprintCount[ap.fingerprint] > 1 && !duplicateAllowed)
            ); // BR-061/071
            _flag(6, amount > m.pay.perRequest && !exceptionValid); // BR-040/041/042
            _flag(7, !active); // BR-062/064
            _flag(11, cancelled); // BR-077
            _flag(14, token.balanceOf(vendor) - beforeRecipient != amount); // ADR-019 V3-3
            _observe(module.PAY(), amount);
            successfulSteps.push(step);
        } catch {}
    }

    function refill(uint256 seed) external {
        I.PaymentApproval memory ap = _approval(seed);
        bytes memory sig = _signature(ap);
        bytes32 step = _step();
        uint256 amount = seed % 3000e6 + 1;
        I.Mandate memory m = module.mandate();
        uint256 beforeUsed = module.usedToday(module.REFILL());
        bool active = _active();
        bool cancelled = module.requestCancelled(ap.requestId);
        bool previouslyRefilled = module.refilledFor(ap.requestId, ap.payingWallet);
        vm.prank(executor);
        try module.refill(ap, sig, step, ap.payingWallet, amount) {
            ++successes;
            _flag(4, token.balanceOf(owner) < module.bufferOf(owner));
            _flag(5, previouslyRefilled || ++stepCount[step] > 1);
            _flag(7, !active);
            _flag(10, token.balanceOf(ap.payingWallet) > ap.amount + module.targetOf(ap.payingWallet)); // BR-036
            _flag(11, cancelled);
            _flag(
                16, amount > m.refill.perRequest || beforeUsed > m.refill.daily || amount > m.refill.daily - beforeUsed
            ); // BR-023
            _observe(module.REFILL(), amount);
            successfulSteps.push(step);
        } catch {}
    }

    function supply(uint256 seed) external {
        bytes32 step = _step();
        uint256 amount = seed % 5000e6 + 1;
        bool active = _active();
        uint256 beforeCash = token.balanceOf(owner);
        vm.prank(executor);
        try module.supply(step, amount) {
            ++successes;
            _flag(7, !active);
            _flag(12, token.balanceOf(owner) < module.bufferOf(owner)); // BR-037 / ADR-019 V3-8
            _flag(13, token.allowance(owner, module.aavePool()) != 0 || beforeCash - token.balanceOf(owner) != amount);
            _observe(module.SUPPLY(), amount);
            _flag(5, ++stepCount[step] > 1);
            successfulSteps.push(step);
        } catch {}
    }

    function withdraw(uint256 seed) external {
        bytes32 step = _step();
        uint256 amount = seed % 5000e6 + 1;
        bool active = _active();
        uint256 beforeCash = token.balanceOf(owner);
        vm.prank(executor);
        try module.withdraw(step, amount) {
            ++successes;
            _flag(7, !active);
            _flag(13, token.allowance(owner, module.aavePool()) != 0 || token.balanceOf(owner) - beforeCash != amount);
            _flag(5, ++stepCount[step] > 1);
            successfulSteps.push(step);
        } catch {}
    }

    function pauseResume(uint256 seed) external {
        if (seed % 97 == 0) {
            vm.prank(owner);
            try module.revoke() {} catch {}
        } else if (seed % 2 == 0) {
            vm.prank(module.mandate().guardian);
            try module.pause() {} catch {}
        } else {
            vm.prank(owner);
            try module.resume() {} catch {}
        }
    }

    function configure(uint256 seed) external {
        I.Mandate memory beforeM = module.mandate();
        uint256 payUsed = module.usedToday(module.PAY());
        uint256 refillUsed = module.usedToday(module.REFILL());
        uint256 supplyUsed = module.usedToday(module.SUPPLY());
        // An owner renews an expired mandate; without this a 366-day warp would
        // leave every later action reverting for the rest of the run.
        uint64 expiresAt = block.timestamp > beforeM.expiresAt ? uint64(block.timestamp + 30 days) : beforeM.expiresAt;
        I.MandateInit memory m = I.MandateInit(
            beforeM.validFrom,
            expiresAt,
            beforeM.payeeCoolingSeconds,
            executor,
            beforeM.guardian,
            I.Limits(uint128(seed % 3000e6 + 1), 10000e6),
            beforeM.refill,
            beforeM.approvalMaxAge,
            beforeM.supply
        );
        vm.prank(owner);
        try module.configureMandate(m) {
            _flag(
                8,
                module.usedToday(module.PAY()) != payUsed || module.usedToday(module.REFILL()) != refillUsed
                    || module.usedToday(module.SUPPLY()) != supplyUsed
                    || module.mandate().version != beforeM.version + 1
            );
        } catch {}
    }

    function grantException(uint256 seed) external {
        I.PaymentApproval memory ap = _approval(seed);
        uint256 amount = ap.earlyAmount > 0 ? ap.earlyAmount : ap.amount;
        vm.prank(owner);
        try module.grantException(ap.requestId, uint128(amount), vendor, uint64(block.timestamp + 1 days)) {} catch {}
    }

    function cancel(uint256 seed) external {
        vm.prank(approver);
        try module.cancelRequest(bytes32(seed % 64 + 1)) {} catch {}
    }

    function advanceTime(uint256 seed) external {
        vm.warp(block.timestamp + (seed % 31 == 0 ? 366 days : seed % 2 days));
    }

    /// @notice Replay a successful step with a fresh signed request, so request replay cannot mask a missing step guard.
    function replayStep(uint256 seed) external {
        if (!_active() || successfulSteps.length == 0) return;
        I.PaymentApproval memory ap = _approval(seed);
        ap.requestId = keccak256(abi.encode("replay request", ++nonce));
        ap.fingerprint = keccak256(abi.encode("replay fingerprint", nonce));
        ap.payingWallet = op1;
        ap.amount = 1;
        ap.earlyAmount = 0;
        (uint64 activeFrom, bool active) = module.payees(vendor);
        if (
            !active || block.timestamp < activeFrom || token.balanceOf(op1) <= module.bufferOf(op1)
                || module.remainingToday(module.PAY()) == 0
        ) return;
        bytes32 step = successfulSteps[seed % successfulSteps.length];
        bytes memory signature = _signature(ap);
        ++replayAttempts;
        vm.prank(executor);
        try module.pay(ap, signature, step) {
            _flag(5, true); // BR-061: the oracle remembers this step independently of stepUsed.
            _observe(module.PAY(), 1);
        } catch {
            ++replayRejections;
        }
    }

    /// @dev Fresh plan ids keep borrowing reachable all run; an eight-id pool was
    /// exhausted after a few consumed authorizations.
    function _newBorrowPlan(uint256 seed) internal returns (bytes32 plan) {
        // Sometimes re-target a known plan so reauthorizing a consumed one is exercised.
        if (borrowPlanIds.length > 0 && seed % 4 == 0) return borrowPlanIds[seed % borrowPlanIds.length];
        plan = keccak256(abi.encode("synthetic handler borrow", ++borrowNonce));
        borrowPlanIds.push(plan);
    }

    function _knownBorrowPlan(uint256 seed) internal view returns (bytes32) {
        if (borrowPlanIds.length == 0 || seed % 5 == 0) {
            return keccak256(abi.encode("unauthorized handler borrow", seed));
        }
        return borrowPlanIds[seed % borrowPlanIds.length];
    }

    function authorizeBorrow(uint256 seed) external {
        bytes32 plan = _newBorrowPlan(seed);
        uint256 amount = seed % 100e6 + 1e6;
        uint64 expiry = uint64(block.timestamp + (seed % 5 == 0 ? 0 : 1 days));
        bool ownerCall = seed % 3 != 0;
        vm.prank(ownerCall ? owner : approver);
        try module.authorizeBorrow(plan, amount, expiry, 15e17, 4e25) {
            _flag(9, !ownerCall);
            _flag(15, !ownerCall || borrowedPlans[plan]); // BR-044: consumed plans cannot be reauthorized.
            if (ownerCall && !borrowedPlans[plan]) {
                expectedBorrowGrants[plan] = I.BorrowAuthorization(amount, expiry, 15e17, 4e25, false);
            }
        } catch {}
    }

    function borrow(uint256 seed) external {
        bytes32 plan = _knownBorrowPlan(seed);
        I.BorrowAuthorization memory grant = expectedBorrowGrants[plan];
        bool active = _active();
        uint256 beforeCash = token.balanceOf(owner);
        ++borrowAttempts;
        vm.prank(executor);
        try module.borrow(plan) {
            ++borrowSuccesses;
            _flag(15, grant.amount == 0 || grant.used || borrowedPlans[plan] || block.timestamp > grant.expiry);
            _flag(15, token.balanceOf(owner) - beforeCash != grant.amount);
            _flag(7, !active);
            borrowedPlans[plan] = true;
            expectedBorrowGrants[plan].used = true;
        } catch {}
    }

    function repay(uint256 seed) external {
        bytes32 plan = keccak256(abi.encode("synthetic handler repay", seed % 8));
        uint256 amount = seed % 100e6 + 1e6;
        if (seed % 3 == 0) {
            vm.prank(owner);
            try module.authorizeRepay(plan, amount, uint64(block.timestamp + 1 days)) {} catch {}
        }
        uint256 beforeCash = token.balanceOf(owner);
        vm.prank(executor);
        try module.repay(plan) {
            _flag(4, token.balanceOf(owner) < module.bufferOf(owner));
            _flag(13, token.balanceOf(owner) > beforeCash || token.allowance(owner, module.aavePool()) != 0);
        } catch {}
    }

    function unauthorizedGovernance(uint256 seed) external {
        address stranger = address(uint160(seed));
        if (stranger == owner || stranger == address(0)) return;
        uint256 beforeBuffer = module.bufferOf(op1);
        vm.prank(stranger);
        try module.setBuffer(op1, 0, 150e6) {
            _flag(9, true);
        } catch {}
        _flag(9, module.bufferOf(op1) != beforeBuffer); // BR-015 / Safe owner authority
    }
}

contract TreasuryInvariantTest is TreasuryFixture {
    struct FuzzSelector {
        address addr;
        bytes4[] selectors;
    }
    TreasuryHandler public handler;

    function setUp() public override {
        super.setUp();
        _safeTx(op1, address(token), abi.encodeWithSignature("transfer(address,uint256)", address(0xD00D), 7000e6));
        _safeTx(op2, address(token), abi.encodeWithSignature("transfer(address,uint256)", address(0xD00D), 9900e6));
        handler = new TreasuryHandler(module, vendor, address(op1), address(op2));
        // Establish non-vacuous successful execution before the randomized campaign.
        handler.pay(1);
        require(handler.successes() == 1, "handler fixture must execute a payment");
        handler.refill(100000003);
        require(handler.successes() == 2, "handler fixture must execute a refill");
        handler.replayStep(1);
        require(handler.replayAttempts() == 1, "handler fixture must attempt step replay");
        handler.borrow(2); // Missing authorization.
        handler.authorizeBorrow(1);
        handler.borrow(1);
        require(handler.borrowSuccesses() == 1, "handler fixture must execute authorized borrowing");
        handler.borrow(1); // Consumed authorization; mutation must trip I15 rather than another guard.
    }

    function targetContracts() external view returns (address[] memory targets) {
        targets = new address[](1);
        targets[0] = address(handler);
    }

    function targetSelectors() external view returns (FuzzSelector[] memory targets) {
        bytes4[] memory selectors = new bytes4[](14);
        selectors[0] = handler.pay.selector;
        selectors[1] = handler.refill.selector;
        selectors[2] = handler.supply.selector;
        selectors[3] = handler.withdraw.selector;
        selectors[4] = handler.pauseResume.selector;
        selectors[5] = handler.configure.selector;
        selectors[6] = handler.grantException.selector;
        selectors[7] = handler.cancel.selector;
        selectors[8] = handler.advanceTime.selector;
        selectors[9] = handler.unauthorizedGovernance.selector;
        selectors[10] = handler.replayStep.selector;
        selectors[11] = handler.authorizeBorrow.selector;
        selectors[12] = handler.borrow.selector;
        selectors[13] = handler.repay.selector;
        targets = new FuzzSelector[](1);
        targets[0] = FuzzSelector(address(handler), selectors);
    }

    function _check(uint256 id) internal view {
        require(handler.violations() & (uint256(1) << id) == 0, "invariant violation");
    }

    function invariant_I01_OnlyCurrentExactApprovals() external view {
        _check(1); // BR-001/003/004
    }

    function invariant_I02_ActiveCooledPayee() external view {
        _check(2); // BR-013/017
    }

    function invariant_I03_TreasuryDailyPayBudget() external view {
        _check(3); // BR-022
    }

    function invariant_I04_WalletFloor() external view {
        _check(4); // BR-030
    }

    function invariant_I05_NoRequestStepOrFingerprintReplay() external view {
        _check(5); // BR-061/071
    }

    function invariant_I06_ExceptionLiftsOnlyPerRequest() external view {
        _check(6); // BR-040/041/042
    }

    function invariant_I07_StatusAndValidityGate() external view {
        _check(7); // BR-062/064
    }

    function invariant_I08_CountersPersistAcrossVersions() external view {
        _check(8); // BR-022
        require(handler.countersMatch(), "ghost accounting");
    }

    function invariant_I09_OnlySafeOwnerGovernance() external view {
        _check(9); // BR-015
    }

    function invariant_I10_RefillBound() external view {
        _check(10); // BR-036
    }

    function invariant_I11_CancelledRequestsNeverExecute() external view {
        _check(11); // BR-077
    }

    function invariant_I12_SupplyPreservesSafeFloor() external view {
        _check(12); // ADR-019 V3-8
    }

    function invariant_I13_FixedPoolCashDeltasAndZeroAllowance() external view {
        _check(13);
        require(
            module.asset() == address(token) && module.aavePool() == address(pool)
                && module.aToken() == address(pool.aToken()),
            "fixed targets"
        );
    }

    function invariant_I14_ExactSignedPaymentOption() external view {
        _check(14); // ADR-019 V3-3
    }

    function invariant_I16_RefillPerRequestAndDailyCaps() external view {
        _check(16); // BR-023
    }

    function invariant_I15_BorrowRequiresUnusedUnexpiredOwnerGrant() external view {
        _check(15); // BR-044 / M04 section 15, P2.
    }
}
