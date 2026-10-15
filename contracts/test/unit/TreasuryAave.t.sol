// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;
import {TreasuryFixture} from "../helpers/TreasuryFixture.sol";
import {TreasuryPilotErrors as E} from "../../src/libraries/TreasuryPilotErrors.sol";
import {ITreasuryPilotModule as I} from "../../src/interfaces/ITreasuryPilotModule.sol";
import {TestRouter} from "../../src/test-assets/TestRouter.sol";
import {TestUSDC} from "../../src/test-assets/TestUSDC.sol";

contract TreasuryAaveTest is TreasuryFixture {
    function testSupplyAcceptsHalfUpAndFloorWithNontrivialIndex() external {
        uint256 beforeCash = token.balanceOf(address(treasury));
        pool.setMintAccounting(15e26, false, 0, 0);
        vm.prank(executor);
        module.supply(bytes32(uint256(1)), 4);
        require(pool.aToken().scaledBalanceOf(address(treasury)) == 3, "half-up mint");
        pool.setMintAccounting(15e26, true, 0, 0);
        vm.prank(executor);
        module.supply(bytes32(uint256(2)), 4);
        require(pool.aToken().scaledBalanceOf(address(treasury)) == 5, "floor mint");
        require(token.balanceOf(address(treasury)) == beforeCash - 8, "exact cash");
        require(token.allowance(address(treasury), address(pool)) == 0, "zero allowance");
    }

    function testSupplyRejectsSharesOutsideTheTwoRoundingModesAndRollsBack() external {
        uint256 beforeCash = token.balanceOf(address(treasury));
        pool.setMintAccounting(15e26, true, 1, 0); // 1 share, below floor=2.
        vm.expectRevert(E.BalanceDeltaMismatch.selector);
        vm.prank(executor);
        module.supply(bytes32(uint256(1)), 4);
        pool.setMintAccounting(15e26, false, 0, 1); // 4 shares, above half-up=3.
        vm.expectRevert(E.BalanceDeltaMismatch.selector);
        vm.prank(executor);
        module.supply(bytes32(uint256(1)), 4);
        require(token.balanceOf(address(treasury)) == beforeCash, "cash rollback");
        require(module.usedToday(module.SUPPLY()) == 0 && !module.stepUsed(bytes32(uint256(1))), "effects rollback");
        require(pool.aToken().scaledBalanceOf(address(treasury)) == 0, "share rollback");
        require(token.allowance(address(treasury), address(pool)) == 0, "allowance rollback");
    }

    function testSupplyAndWithdrawExactCashAndClearAllowance() external {
        uint256 cash = token.balanceOf(address(treasury));
        vm.prank(executor);
        module.supply(bytes32(uint256(1)), 500e6);
        require(token.balanceOf(address(treasury)) == cash - 500e6, "supply cash");
        require(pool.aToken().balanceOf(address(treasury)) == 500e6, "aToken cash");
        require(token.allowance(address(treasury), address(pool)) == 0, "supply allowance");
        require(
            module.usedToday(module.SUPPLY()) == 500e6 && module.usedToday(module.PAY()) == 0, "separate supply cap"
        );
        vm.prank(executor);
        module.withdraw(bytes32(uint256(2)), 500e6);
        require(
            token.balanceOf(address(treasury)) == cash && pool.aToken().balanceOf(address(treasury)) == 0,
            "withdraw exact"
        );
        require(token.allowance(address(treasury), address(pool)) == 0, "withdraw allowance");
    }

    function testSupplyFloorPerTxDailyReplayAndAccess() external {
        vm.expectRevert(E.NotExecutor.selector);
        module.supply(bytes32(uint256(1)), 1);
        vm.expectRevert(E.InvalidAmount.selector);
        vm.prank(executor);
        module.supply(bytes32(uint256(1)), 0);
        vm.expectRevert(E.OverSupplyPerTx.selector);
        vm.prank(executor);
        module.supply(bytes32(uint256(1)), 5000e6 + 1);
        _owner(abi.encodeCall(module.setBuffer, (address(treasury), token.balanceOf(address(treasury)) - 500e6, 0)));
        vm.expectRevert(E.SupplyFloorBreach.selector);
        vm.prank(executor);
        module.supply(bytes32(uint256(1)), 500e6 + 1);
        vm.prank(executor);
        module.supply(bytes32(uint256(1)), 500e6);
        require(token.balanceOf(address(treasury)) == module.bufferOf(address(treasury)), "supply exactly floor");
        vm.expectRevert(E.StepAlreadyExecuted.selector);
        vm.prank(executor);
        module.supply(bytes32(uint256(1)), 1);
        _owner(abi.encodeCall(module.setBuffer, (address(treasury), 1000e6, 0)));
        config.supply = I.Limits(500e6, 500e6);
        _owner(abi.encodeCall(module.configureMandate, (config)));
        vm.expectRevert(E.OverSupplyDaily.selector);
        vm.prank(executor);
        module.supply(bytes32(uint256(2)), 1);
    }

    function testWithdrawChecksReplayBalanceAndPause() external {
        vm.expectRevert(E.InsufficientAToken.selector);
        vm.prank(executor);
        module.withdraw(bytes32(uint256(1)), 1);
        vm.prank(executor);
        module.supply(bytes32(uint256(1)), 500e6);
        vm.expectRevert(E.StepAlreadyExecuted.selector);
        vm.prank(executor);
        module.withdraw(bytes32(uint256(1)), 1);
        _owner(abi.encodeCall(module.pause, ()));
        vm.expectRevert(E.MandatePaused.selector);
        vm.prank(executor);
        module.withdraw(bytes32(uint256(2)), 1);
    }

    function testOwnerAuthorizedBorrowAndRepayAreOneUse() external {
        bytes32 plan = keccak256("exact synthetic owner-approved borrow plan");
        vm.expectRevert(E.BorrowNotAuthorized.selector);
        vm.prank(executor);
        module.borrow(plan);
        _owner(abi.encodeCall(module.authorizeBorrow, (plan, 100e6, uint64(block.timestamp + 1 days), 15e17, 4e25)));
        uint256 cash = token.balanceOf(address(treasury));
        vm.prank(executor);
        module.borrow(plan);
        require(
            token.balanceOf(address(treasury)) == cash + 100e6 && pool.debt(address(treasury)) == 100e6, "borrow amount"
        );
        vm.expectRevert(E.BorrowNotAuthorized.selector);
        vm.prank(executor);
        module.borrow(plan);
        vm.expectRevert(E.AuthorizationAlreadyUsed.selector);
        vm.prank(address(treasury));
        module.authorizeBorrow(plan, 100e6, uint64(block.timestamp + 1 days), 15e17, 4e25);
        bytes32 repayPlan = keccak256("exact synthetic repayment plan");
        vm.expectRevert(E.RepayNotAuthorized.selector);
        vm.prank(executor);
        module.repay(repayPlan);
        _owner(abi.encodeCall(module.authorizeRepay, (repayPlan, 100e6, uint64(block.timestamp + 1 days))));
        vm.prank(executor);
        module.repay(repayPlan);
        require(token.balanceOf(address(treasury)) == cash && pool.debt(address(treasury)) == 0, "repay amount");
        require(token.allowance(address(treasury), address(pool)) == 0, "repay allowance");
        vm.expectRevert(E.RepayNotAuthorized.selector);
        vm.prank(executor);
        module.repay(repayPlan);
    }

    function testBorrowRejectsHealthFactorBeforeAndAfterAndRollsBack() external {
        bytes32 plan = bytes32(uint256(1));
        _owner(abi.encodeCall(module.authorizeBorrow, (plan, 100e6, uint64(block.timestamp + 1 days), 15e17, 4e25)));
        pool.setHealthFactor(14e17);
        vm.expectRevert(E.HealthFactorTooLow.selector);
        vm.prank(executor);
        module.borrow(plan);
        pool.setHealthFactor(2e18);
        pool.setHealthFactorAfterBorrow(14e17);
        vm.expectRevert(E.HealthFactorTooLow.selector);
        vm.prank(executor);
        module.borrow(plan);
        (,,,, bool used) = module.borrowAuthorizations(plan);
        require(!used && pool.debt(address(treasury)) == 0, "failed borrow changed state");
    }

    function testBorrowRejectsExpiredGrantAndExcessRate() external {
        bytes32 plan = bytes32(uint256(1));
        _owner(abi.encodeCall(module.authorizeBorrow, (plan, 100e6, uint64(block.timestamp), 15e17, 1e25)));
        vm.expectRevert(E.BorrowRateTooHigh.selector);
        vm.prank(executor);
        module.borrow(plan);
        vm.warp(block.timestamp + 1);
        vm.expectRevert(E.AuthorizationExpired.selector);
        vm.prank(executor);
        module.borrow(plan);
    }

    function testRepayPartialDebtReturnsUnusedApprovalAndRespectsFloor() external {
        bytes32 borrowPlan = bytes32(uint256(1));
        bytes32 repayPlan = bytes32(uint256(2));
        _owner(
            abi.encodeCall(module.authorizeBorrow, (borrowPlan, 100e6, uint64(block.timestamp + 1 days), 15e17, 4e25))
        );
        vm.prank(executor);
        module.borrow(borrowPlan);
        _owner(abi.encodeCall(module.authorizeRepay, (repayPlan, 200e6, uint64(block.timestamp + 1 days))));
        uint256 beforeCash = token.balanceOf(address(treasury));
        _owner(abi.encodeCall(module.setBuffer, (address(treasury), beforeCash, 0)));
        vm.expectRevert(E.SourceBufferBreach.selector);
        vm.prank(executor);
        module.repay(repayPlan);
        _owner(abi.encodeCall(module.setBuffer, (address(treasury), 1000e6, 0)));
        vm.prank(executor);
        module.repay(repayPlan);
        require(token.balanceOf(address(treasury)) == beforeCash - 100e6, "actual outstanding debt");
        require(token.allowance(address(treasury), address(pool)) == 0, "partial repay allowance");
    }

    function testAT04AndAT13SwapFixedPairBudgetMinOutAndZeroAllowance() external {
        TestUSDC output = new TestUSDC();
        TestRouter router = new TestRouter(address(token), address(output), 2, 1);
        output.mint(address(router), 1000e6);
        vm.expectRevert(E.RouterNotAllowed.selector);
        vm.prank(executor);
        module.swapForGas(bytes32(uint256(1)), 1e6, 1);
        _owner(abi.encodeCall(module.configureSwap, (address(router), address(output), I.Limits(100e6, 150e6))));
        vm.prank(executor);
        module.swapForGas(bytes32(uint256(1)), 100e6, 200e6);
        require(
            output.balanceOf(address(treasury)) == 200e6 && token.allowance(address(treasury), address(router)) == 0,
            "swap result"
        );
        vm.expectRevert(E.OverSwapDaily.selector);
        vm.prank(executor);
        module.swapForGas(bytes32(uint256(2)), 51e6, 1);
        vm.expectRevert(E.OverSwapPerTx.selector);
        vm.prank(executor);
        module.swapForGas(bytes32(uint256(2)), 101e6, 1);
        vm.expectRevert(E.TransferFailed.selector);
        vm.prank(executor);
        module.swapForGas(bytes32(uint256(2)), 1e6, 3e6);
        require(!module.stepUsed(bytes32(uint256(2))), "failed swap consumed step");
        require(address(treasury).balance == 0, "native transfer");
    }

    function testWrongRouterPairCannotBeAllowed() external {
        TestUSDC output = new TestUSDC();
        TestRouter router = new TestRouter(address(output), address(token), 1, 1);
        vm.expectRevert(E.RouterNotAllowed.selector);
        vm.prank(address(treasury));
        module.configureSwap(address(router), address(output), I.Limits(100e6, 150e6));
    }
}
