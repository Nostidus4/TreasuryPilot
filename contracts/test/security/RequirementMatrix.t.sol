// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;
import {TreasuryFixture} from "../helpers/TreasuryFixture.sol";
import {Vm} from "../helpers/Vm.sol";
import {ITreasuryPilotModule as I} from "../../src/interfaces/ITreasuryPilotModule.sol";
import {TreasuryPilotErrors as E} from "../../src/libraries/TreasuryPilotErrors.sol";
import {ISafeWallet, ISafeProxyFactory} from "../../src/interfaces/ISafeWallet.sol";

/// @notice SC-007/009/011/020 negative cases and event compatibility at the real Safe boundary.
contract RequirementMatrixTest is TreasuryFixture {
    function testGuardianSafeOneOfTwoCanPauseButCannotResume() external {
        address singleton = _deployArtifact("Safe.sol:Safe");
        ISafeProxyFactory proxies = ISafeProxyFactory(_deployArtifact("SafeProxyFactory.sol:SafeProxyFactory"));
        address[] memory owners = new address[](2);
        owners[0] = address(this);
        owners[1] = guardian;
        ISafeWallet guardianSafe = ISafeWallet(
            proxies.createProxyWithNonce(
                singleton,
                abi.encodeCall(
                    ISafeWallet.setup,
                    (owners, 1, address(0), bytes(""), address(0), address(0), 0, payable(address(0)))
                ),
                99
            )
        );
        config.guardian = address(guardianSafe);
        _owner(abi.encodeCall(module.configureMandate, (config)));
        _safeTx(guardianSafe, address(module), abi.encodeCall(module.pause, ()));
        _expectPayError(_approval(1, 1), E.NotActive.selector);
        vm.expectRevert(E.NotOwner.selector);
        vm.prank(address(guardianSafe));
        module.resume();
        _owner(abi.encodeCall(module.resume, ()));
    }

    function testDirectArbitrarySelectorsAndNativeValueCannotExecute() external {
        (bool arbitrary,) = address(module)
            .call(abi.encodeWithSignature("execute(address,uint256,bytes)", address(token), 0, bytes("")));
        require(!arbitrary, "generic execution accepted");
        // Send the value as the real executor with the step _assertRejected checks, so
        // the call can only fail because `pay` is non-payable, not on NotExecutor.
        vm.deal(executor, 1);
        I.PaymentApproval memory ap = _approval(1, 1);
        bytes memory call = abi.encodeCall(module.pay, (ap, _sign(ap), keccak256("rejected step"), ap.amount));
        vm.prank(executor);
        (bool native, bytes memory reason) = address(module).call{value: 1}(call);
        require(!native && reason.length == 0, "native value not rejected by the non-payable check");
        require(address(module).balance == 0 && executor.balance == 1, "native value accepted");
        _assertRejected(ap);
    }

    function testDirectExceptionCannotLiftPayeeRules() external {
        I.PaymentApproval memory ap = _approval(1, 2500e6);
        _grant(1, vendor, uint64(block.timestamp + 1 days));
        _owner(abi.encodeCall(module.deactivatePayee, (vendor)));
        _expectPayError(ap, E.PayeeUnknown.selector);
        _owner(abi.encodeCall(module.addPayee, (vendor)));
        _expectPayError(ap, E.PayeeCooling.selector);
        _assertRejected(ap);
    }

    function testDirectPreviouslySignedStepUsesExecutionDayBudget() external {
        config.pay = I.Limits(100e6, 100e6);
        _owner(abi.encodeCall(module.configureMandate, (config)));
        _pay(_approval(1, 100e6), bytes32(uint256(1)));
        uint256 previousDay = block.timestamp / 1 days;
        I.PaymentApproval memory ap = _approval(2, 100e6);
        bytes memory signature = _sign(ap);
        vm.warp((previousDay + 1) * 1 days);
        vm.prank(executor);
        module.pay(ap, signature, bytes32(uint256(2)), ap.amount);
        require(module.usedToday(module.PAY()) == 100e6, "execution day cap");
        require(
            module.usedOn(keccak256(abi.encode(module.PAY(), address(token), previousDay))) == 100e6,
            "previous day preserved"
        );
    }

    function _grant(uint256 request, address payee, uint64 expiry) internal {
        _owner(abi.encodeCall(module.grantException, (bytes32(request), uint128(2500e6), payee, expiry)));
    }

    function _assertRejected(I.PaymentApproval memory ap) internal view {
        require(!module.requestPaid(ap.requestId) && !module.stepUsed(keccak256("rejected step")), "replay rollback");
        require(module.usedToday(module.PAY()) == 0 && token.balanceOf(vendor) == 0, "payment rollback");
        require(token.balanceOf(address(op1)) == 10000e6, "cash rollback");
        (,,,, bool used) = module.exceptions(ap.requestId);
        require(!used, "grant rollback");
    }

    function testDirectExceptionWrongPayeeRevertsAndPreservesGrant() external {
        I.PaymentApproval memory ap = _approval(1, 2500e6);
        _grant(1, address(0xABCD), uint64(block.timestamp + 1 days));
        _expectPayError(ap, E.ExceptionInvalid.selector);
        _assertRejected(ap);
    }

    function testDirectExpiredExceptionRevertsAndPreservesGrant() external {
        I.PaymentApproval memory ap = _approval(1, 2500e6);
        _grant(1, vendor, uint64(block.timestamp));
        vm.warp(block.timestamp + 1);
        _expectPayError(ap, E.ExceptionInvalid.selector);
        _assertRejected(ap);
    }

    function testDirectDifferentRequestCannotUseOwnerException() external {
        _grant(1, vendor, uint64(block.timestamp + 1 days));
        I.PaymentApproval memory ap = _approval(2, 2500e6);
        _expectPayError(ap, E.OverPerRequestLimit.selector);
        _assertRejected(ap);
        (uint128 amount,,,, bool used) = module.exceptions(bytes32(uint256(1)));
        require(amount == 2500e6 && !used, "other grant changed");
    }

    function testDirectRevokedExceptionCannotAuthorizePayment() external {
        _grant(1, vendor, uint64(block.timestamp + 1 days));
        _owner(abi.encodeCall(module.revokeException, (bytes32(uint256(1)))));
        I.PaymentApproval memory ap = _approval(1, 2500e6);
        _expectPayError(ap, E.OverPerRequestLimit.selector);
        _assertRejected(ap);
    }

    function testDirectRefillCapsAndExactDailyBoundaryWithRollback() external {
        config.refill = I.Limits(500e6, 600e6);
        _owner(abi.encodeCall(module.configureMandate, (config)));
        _safeTx(op1, address(token), abi.encodeWithSignature("transfer(address,uint256)", address(0xD00D), 10000e6));
        I.PaymentApproval memory ap = _approval(1, 1000e6);
        bytes memory sig = _sign(ap);
        vm.expectRevert(E.OverRefillPerRequest.selector);
        vm.prank(executor);
        module.refill(ap, sig, bytes32(uint256(1)), address(op1), 500e6 + 1);
        require(
            !module.refilledFor(ap.requestId, address(op1)) && !module.stepUsed(bytes32(uint256(1))), "per-tx effects"
        );
        require(module.usedToday(module.REFILL()) == 0 && token.balanceOf(address(op1)) == 0, "per-tx rollback");
        _refill(ap, bytes32(uint256(1)), 500e6);
        ap = _approval(2, 1000e6);
        sig = _sign(ap);
        uint256 beforeCash = token.balanceOf(address(treasury));
        vm.expectRevert(E.OverRefillDaily.selector);
        vm.prank(executor);
        module.refill(ap, sig, bytes32(uint256(2)), address(op1), 100e6 + 1);
        require(
            !module.refilledFor(ap.requestId, address(op1)) && !module.stepUsed(bytes32(uint256(2))), "daily effects"
        );
        require(
            token.balanceOf(address(treasury)) == beforeCash && token.balanceOf(address(op1)) == 500e6,
            "daily cash rollback"
        );
        require(module.usedToday(module.REFILL()) == 500e6 && module.usedToday(module.PAY()) == 0, "separate counters");
        _refill(ap, bytes32(uint256(2)), 100e6);
        require(module.usedToday(module.REFILL()) == 600e6, "exact daily cap");
    }

    function testBorrowEventMatchesChainReaderTopicAndPayload() external {
        bytes32 plan = keccak256("synthetic event plan");
        _owner(abi.encodeCall(module.authorizeBorrow, (plan, 100e6, uint64(block.timestamp + 1 days), 15e17, 4e25)));
        vm.recordLogs();
        vm.prank(executor);
        module.borrow(plan);
        Vm.Log[] memory logs = vm.getRecordedLogs();
        uint256 matches;
        for (uint256 i; i < logs.length; ++i) {
            if (logs[i].emitter != address(module)) continue;
            require(
                logs[i].topics.length == 2 && logs[i].topics[0] == keccak256("BorrowExecuted(bytes32,uint256)"),
                "borrow topic"
            );
            require(logs[i].topics[1] == plan && abi.decode(logs[i].data, (uint256)) == 100e6, "borrow payload");
            ++matches;
        }
        require(matches == 1, "one borrow event");
    }

    function testFactoryEventContainsCallingSafeCloneAndAsset() external {
        address[] memory ops = new address[](1);
        ops[0] = address(op1);
        address[] memory approvers = new address[](1);
        approvers[0] = approver;
        I.BufferInit[] memory buffers = new I.BufferInit[](2);
        buffers[0] = I.BufferInit(address(treasury), 1000e6, 0);
        buffers[1] = I.BufferInit(address(op1), 10e6, 150e6);
        vm.recordLogs();
        _safeTx(
            treasury,
            address(factory),
            abi.encodeCall(factory.create, (address(token), ops, config, approvers, buffers, address(pool)))
        );
        Vm.Log[] memory logs = vm.getRecordedLogs();
        uint256 matches;
        for (uint256 i; i < logs.length; ++i) {
            if (logs[i].emitter != address(factory)) continue;
            require(
                logs[i].topics.length == 3
                    && logs[i].topics[0] == keccak256("TreasuryModuleCreated(address,address,address)"),
                "factory topic"
            );
            require(address(uint160(uint256(logs[i].topics[1]))) == address(treasury), "factory caller");
            require(address(uint160(uint256(logs[i].topics[2]))).code.length != 0, "factory clone");
            require(abi.decode(logs[i].data, (address)) == address(token), "factory asset");
            ++matches;
        }
        require(matches == 1, "one factory event");
    }
}
