// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;
import {TreasuryFixture} from "../helpers/TreasuryFixture.sol";
import {TreasuryPilotErrors as E} from "../../src/libraries/TreasuryPilotErrors.sol";
import {ITreasuryPilotModule as I} from "../../src/interfaces/ITreasuryPilotModule.sol";
import {TreasuryPilotModule} from "../../src/TreasuryPilotModule.sol";
import {ISafeWallet} from "../../src/interfaces/ISafeWallet.sol";

contract TreasuryGovernanceTest is TreasuryFixture {
    function testFactoryCreatesConfiguredCloneAndEmitsStableAuthority() external view {
        require(module.safeT() == address(treasury) && module.asset() == address(token), "identity");
        require(factory.implementation() == address(implementation), "implementation");
        require(module.isOperational(address(op1)) && module.isOperational(address(op2)), "operational");
        require(module.aavePool() == address(pool) && module.aToken() == address(pool.aToken()), "aave");
        require(module.mandate().version == 1 && module.approverCount() == 1, "configuration");
        require(module.bufferOf(address(treasury)) == 1000e6, "floor");
    }

    function testImplementationAndCloneCannotBeInitializedAgain() external {
        address[] memory empty = new address[](0);
        I.BufferInit[] memory buffers = new I.BufferInit[](0);
        vm.expectRevert(E.AlreadyInitialized.selector);
        implementation.initialize(address(treasury), address(token), empty, config, empty, buffers, address(pool));
        vm.expectRevert(E.AlreadyInitialized.selector);
        module.initialize(address(treasury), address(token), empty, config, empty, buffers, address(pool));
    }

    function testFactoryRejectsEOACreator() external {
        address[] memory empty = new address[](0);
        I.BufferInit[] memory buffers = new I.BufferInit[](0);
        vm.expectRevert(E.NotOwner.selector);
        vm.prank(executor);
        factory.create(address(token), empty, config, empty, buffers, address(pool));
    }

    function testTwoTreasuriesHaveIndependentStorageAndDomains() external {
        ISafeWallet second = deployOneOfOneSafe(address(this), 4);
        address[] memory ops = new address[](1);
        ops[0] = address(op1);
        address[] memory approvers = new address[](1);
        approvers[0] = approver;
        I.BufferInit[] memory buffers = new I.BufferInit[](2);
        buffers[0] = I.BufferInit(address(second), 900e6, 0);
        buffers[1] = I.BufferInit(address(op1), 20e6, 200e6);
        vm.prank(address(second));
        TreasuryPilotModule other =
            TreasuryPilotModule(factory.create(address(token), ops, config, approvers, buffers, address(pool)));
        require(other.safeT() == address(second) && other.bufferOf(address(second)) == 900e6, "second config");
        require(module.bufferOf(address(op1)) == 10e6 && other.bufferOf(address(op1)) == 20e6, "shared storage");
        require(other.domainSeparator() != module.domainSeparator(), "shared domain");
        _owner(abi.encodeCall(module.setBuffer, (address(op1), 15e6, 150e6)));
        require(other.bufferOf(address(op1)) == 20e6, "cross treasury mutation");
    }

    function testGovernanceRejectsExecutorGuardianAndStranger() external {
        address[3] memory callers = [executor, guardian, address(0x1234)];
        for (uint256 i; i < callers.length; ++i) {
            vm.expectRevert(E.NotOwner.selector);
            vm.prank(callers[i]);
            module.configureMandate(config);
            vm.expectRevert(E.NotOwner.selector);
            vm.prank(callers[i]);
            module.addPayee(address(0xB123));
            vm.expectRevert(E.NotOwner.selector);
            vm.prank(callers[i]);
            module.setBuffer(address(op1), 0, 0);
        }
    }

    function testMandateValidationMatrix() external {
        I.MandateInit memory m = config;
        m.expiresAt = m.validFrom;
        _expectInvalid(m, "expiresAt");
        m = config;
        m.executor = address(0);
        _expectInvalid(m, "executor");
        m = config;
        m.payeeCoolingSeconds = 0;
        _expectInvalid(m, "payeeCoolingSeconds");
        m = config;
        m.pay.perRequest = m.pay.daily + 1;
        _expectInvalid(m, "pay");
        m = config;
        m.refill.perRequest = m.refill.daily + 1;
        _expectInvalid(m, "refill");
        m = config;
        m.supply.perRequest = m.supply.daily + 1;
        _expectInvalid(m, "supply");
        m = config;
        m.approvalMaxAge = 0;
        _expectInvalid(m, "approvalMaxAge");
    }

    function _expectInvalid(I.MandateInit memory m, bytes32 field) internal {
        vm.expectRevert(abi.encodeWithSelector(E.InvalidMandate.selector, field));
        vm.prank(address(treasury));
        module.configureMandate(m);
    }

    function testChangingVersionDoesNotResetCounters() external {
        _pay(_approval(1, 100e6), bytes32(uint256(1)));
        uint256 beforeUsed = module.usedToday(module.PAY());
        _owner(abi.encodeCall(module.configureMandate, (config)));
        require(module.mandate().version == 2 && module.usedToday(module.PAY()) == beforeUsed, "counter reset");
    }

    function testApproversCannotBecomeEmptyAndUpdatesAreIdempotent() external {
        address[] memory add = new address[](1);
        add[0] = approver;
        address[] memory empty = new address[](0);
        _owner(abi.encodeCall(module.setApprovers, (add, empty)));
        require(module.approverCount() == 1, "duplicate approver counted");
        vm.expectRevert(E.NoApprovers.selector);
        vm.prank(address(treasury));
        module.setApprovers(empty, add);
        require(module.isApprover(approver), "failed update not rolled back");
    }

    function testBufferMustBelongToKnownWalletAndOperationalTargetCoversFloor() external {
        vm.expectRevert(E.UnknownWallet.selector);
        vm.prank(address(treasury));
        module.setBuffer(vendor, 1, 1);
        vm.expectRevert(E.TargetBelowBuffer.selector);
        vm.prank(address(treasury));
        module.setBuffer(address(op1), 2, 1);
    }

    function testPayeeCoolingBoundaryAndReactivation() external {
        _owner(abi.encodeCall(module.addPayee, (vendor)));
        (uint64 activeFrom,) = module.payees(vendor);
        _expectPayError(_approval(1, 1e6), E.PayeeCooling.selector);
        vm.warp(activeFrom);
        _pay(_approval(1, 1e6), bytes32(uint256(1)));
        _owner(abi.encodeCall(module.deactivatePayee, (vendor)));
        _expectPayError(_approval(2, 1e6), E.PayeeUnknown.selector);
        _owner(abi.encodeCall(module.addPayee, (vendor)));
        _expectPayError(_approval(2, 1e6), E.PayeeCooling.selector);
    }

    function testTreasuryWalletsAndZeroCannotBePayees() external {
        address[4] memory invalid = [address(treasury), address(op1), address(op2), address(0)];
        for (uint256 i; i < invalid.length; ++i) {
            vm.expectRevert(E.InvalidPayee.selector);
            vm.prank(address(treasury));
            module.addPayee(invalid[i]);
        }
    }

    function testGuardianCanPauseButOnlyOwnerCanResumeOrRevoke() external {
        vm.prank(guardian);
        module.pause();
        vm.prank(guardian);
        module.pause();
        _expectPayError(_approval(1, 1e6), E.NotActive.selector);
        vm.expectRevert(E.NotOwner.selector);
        vm.prank(guardian);
        module.resume();
        _owner(abi.encodeCall(module.resume, ()));
        _owner(abi.encodeCall(module.revoke, ()));
        _owner(abi.encodeCall(module.configureMandate, (config)));
        _expectPayError(_approval(1, 1e6), E.NotActive.selector);
        vm.expectRevert(E.NotPaused.selector);
        vm.prank(address(treasury));
        module.resume();
        vm.expectRevert(E.Revoked.selector);
        vm.prank(guardian);
        module.pause();
    }

    function testApproverAndOwnerCanCancelDuringPauseButStrangerCannot() external {
        _owner(abi.encodeCall(module.pause, ()));
        vm.prank(approver);
        module.cancelRequest(bytes32(uint256(1)));
        vm.prank(approver);
        module.cancelRequest(bytes32(uint256(1)));
        _owner(abi.encodeCall(module.cancelRequest, (bytes32(uint256(2)))));
        vm.expectRevert(E.NotOwnerOrApprover.selector);
        vm.prank(executor);
        module.cancelRequest(bytes32(uint256(3)));
        _owner(abi.encodeCall(module.resume, ()));
        _expectPayError(_approval(1, 1e6), E.RequestCancelled.selector);
        I.PaymentApproval memory ap = _approval(1, 1e6);
        bytes memory sig = _sign(ap);
        vm.expectRevert(E.RequestCancelled.selector);
        vm.prank(executor);
        module.refill(ap, sig, bytes32(uint256(3)), address(op1), 1e6);
        _pay(_approval(4, 1e6), bytes32(uint256(4)));
        vm.expectRevert(E.AlreadyPaid.selector);
        vm.prank(approver);
        module.cancelRequest(bytes32(uint256(4)));
    }
}
