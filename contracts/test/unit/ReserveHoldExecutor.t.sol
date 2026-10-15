// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;
import {TreasuryFixture} from "../helpers/TreasuryFixture.sol";
import {ReserveHoldExecutor} from "../../src/ReserveHoldExecutor.sol";
import {TreasuryPilotErrors as E} from "../../src/libraries/TreasuryPilotErrors.sol";
import {ITreasuryPilotModule as I} from "../../src/interfaces/ITreasuryPilotModule.sol";

contract ReserveHoldExecutorTest is TreasuryFixture {
    ReserveHoldExecutor internal gate;
    bytes32 internal constant STEP = keccak256("step");

    function setUp() public override {
        super.setUp();
        gate = new ReserveHoldExecutor(module, executor);
        I.MandateInit memory m = config;
        m.executor = address(gate);
        m.validFrom = uint64(block.timestamp - 300);
        _owner(abi.encodeCall(module.configureMandate, (m)));
    }

    function _reserve(uint256 id, address wallet, uint256 amount) internal {
        vm.prank(executor);
        gate.reserve(bytes32(id), address(token), wallet, amount);
    }

    function _gatePay(uint256 id, uint256 amount, bytes32 step, bytes4 err) internal {
        I.PaymentApproval memory ap = _approval(id, amount);
        bytes memory sig = _sign(ap);
        if (err != bytes4(0)) vm.expectRevert(err);
        vm.prank(executor);
        gate.pay(ap, sig, step, amount);
    }

    function testReserveToHoldKeepsCommittedTotal() external {
        _reserve(1, address(op1), 4000e6);
        require(gate.reservedOf(address(token), address(op1)) == 4000e6, "R");
        vm.prank(executor);
        gate.beginExecution(bytes32(uint256(1)));
        require(gate.reservedOf(address(token), address(op1)) == 0, "R cleared");
        require(gate.heldOf(address(token), address(op1)) == 4000e6, "L");
        require(gate.committedOf(address(token), address(op1)) == 4000e6, "no double count");
        vm.prank(executor);
        vm.expectRevert(ReserveHoldExecutor.NothingToHold.selector);
        gate.beginExecution(bytes32(uint256(1)));
    }

    function testReserveCannotExceedBalanceMinusBufferAndCommitments() external {
        _reserve(1, address(op1), 9000e6);
        vm.prank(executor);
        vm.expectRevert(ReserveHoldExecutor.InsufficientUncommitted.selector);
        gate.reserve(bytes32(uint256(2)), address(token), address(op1), 991e6); // free is 10000 - 10 - 9000
        _reserve(2, address(op1), 990e6);
        vm.prank(executor);
        vm.expectRevert(ReserveHoldExecutor.AlreadyRegistered.selector);
        gate.reserve(bytes32(uint256(2)), address(token), address(op1), 1);
    }

    function testReserveGuards() external {
        vm.expectRevert(E.NotExecutor.selector);
        gate.reserve(bytes32(uint256(1)), address(token), address(op1), 1);
        vm.startPrank(executor);
        vm.expectRevert(E.NotOperationalWallet.selector);
        gate.reserve(bytes32(uint256(1)), address(token), address(0xBAD), 1);
        vm.expectRevert(E.InvalidAmount.selector);
        gate.reserve(bytes32(uint256(1)), address(token), address(op1), 0);
        vm.stopPrank();
    }

    function testOtherRequestCannotSpendReservedFunds() external {
        _reserve(1, address(op1), 9000e6);
        _gatePay(2, 1500e6, STEP, ReserveHoldExecutor.CommittedFundsBreach.selector);
        _gatePay(2, 900e6, STEP, bytes4(0));
        require(token.balanceOf(address(op1)) == 9100e6, "only the free part moved");
        require(gate.committedOf(address(token), address(op1)) == 9000e6, "reserve intact");
    }

    function testHeldFundsAreProtectedToo() external {
        _reserve(1, address(op1), 9000e6);
        vm.prank(executor);
        gate.beginExecution(bytes32(uint256(1)));
        _gatePay(2, 1500e6, STEP, ReserveHoldExecutor.CommittedFundsBreach.selector);
    }

    function testPayingOwnRequestConsumesCommitment() external {
        _reserve(1, address(op1), 1500e6);
        vm.prank(executor);
        gate.beginExecution(bytes32(uint256(1)));
        _gatePay(1, 1500e6, STEP, bytes4(0));
        require(gate.committedOf(address(token), address(op1)) == 0, "released on payment");
        (address wallet,,,) = gate.commitments(bytes32(uint256(1)));
        require(wallet == address(0), "commitment deleted");
        vm.prank(executor);
        vm.expectRevert(E.RequestAlreadyPaid.selector);
        gate.reserve(bytes32(uint256(1)), address(token), address(op1), 1);
    }

    function testSupplyCannotTakeSafeBelowBufferPlusCommitments() external {
        _reserve(1, address(treasury), 27000e6); // Safe T: 30000 - 1000 buffer - 27000 = 2000 free
        vm.prank(executor);
        vm.expectRevert(ReserveHoldExecutor.CommittedFundsBreach.selector);
        gate.supply(STEP, 3000e6);
        vm.prank(executor);
        gate.supply(STEP, 2000e6);
    }

    function testRefillCannotDrainReservedSafeFunds() external {
        _reserve(1, address(treasury), 28000e6);
        vm.prank(address(op1));
        token.transfer(address(1), 9990e6);
        I.PaymentApproval memory ap = _approval(7, 1500e6);
        bytes memory sig = _sign(ap);
        vm.prank(executor);
        vm.expectRevert(ReserveHoldExecutor.CommittedFundsBreach.selector);
        gate.refill(ap, sig, STEP, address(treasury), address(op1), 1500e6); // free is 1000, so 1500 breaches
    }

    function testHoldReleaseNeedsKnownOutcome() external {
        _reserve(1, address(op1), 1000e6);
        vm.prank(executor);
        gate.beginExecution(bytes32(uint256(1)));
        vm.warp(block.timestamp + 365 days); // a timeout never releases
        require(gate.heldOf(address(token), address(op1)) == 1000e6, "still held");
        vm.prank(executor);
        vm.expectRevert(ReserveHoldExecutor.ReleaseNotAllowed.selector);
        gate.release(bytes32(uint256(1)));
        vm.expectRevert(ReserveHoldExecutor.NotOwner.selector);
        gate.release(bytes32(uint256(1)));
        // Cancellation is a known on-chain outcome.
        vm.prank(approver);
        module.cancelRequest(bytes32(uint256(1)));
        vm.prank(executor);
        gate.release(bytes32(uint256(1)));
        require(gate.committedOf(address(token), address(op1)) == 0, "released");
    }

    function testOperatorCannotReleaseReserveUntilPaidOrCancelled() external {
        _reserve(1, address(op1), 1000e6);
        vm.prank(executor);
        vm.expectRevert(ReserveHoldExecutor.ReleaseNotAllowed.selector);
        gate.release(bytes32(uint256(1)));
        vm.prank(approver);
        module.cancelRequest(bytes32(uint256(1)));
        vm.prank(executor);
        gate.release(bytes32(uint256(1)));
    }

    function testOwnerReleasesAnyCommitmentUnconditionally() external {
        _reserve(1, address(op1), 1000e6);
        _reserve(2, address(op1), 1000e6);
        vm.prank(executor);
        gate.beginExecution(bytes32(uint256(2)));
        vm.prank(address(treasury));
        gate.release(bytes32(uint256(1)));
        vm.prank(address(treasury));
        gate.release(bytes32(uint256(2)));
        require(gate.committedOf(address(token), address(op1)) == 0, "all released");
        vm.prank(address(treasury));
        vm.expectRevert(ReserveHoldExecutor.NotRegistered.selector);
        gate.release(bytes32(uint256(2)));
    }

    function testReleaseManyIsOwnerOnlyAndSkipsUnregistered() external {
        _reserve(1, address(op1), 1000e6);
        _reserve(2, address(treasury), 1000e6);
        bytes32[] memory ids = new bytes32[](3);
        ids[0] = bytes32(uint256(1));
        ids[1] = bytes32(uint256(99));
        ids[2] = bytes32(uint256(2));
        vm.prank(executor);
        vm.expectRevert(ReserveHoldExecutor.NotOwner.selector);
        gate.releaseMany(ids);
        vm.prank(address(treasury));
        gate.releaseMany(ids);
        require(gate.committedOf(address(token), address(op1)) == 0, "op1 released");
        require(gate.committedOf(address(token), address(treasury)) == 0, "treasury released");
    }

    function testPayLeavesCommitmentOnAnotherWalletUntilReleased() external {
        _reserve(2, address(treasury), 1000e6); // request 2 is paid from op1 (see _approval)
        _gatePay(2, 500e6, STEP, bytes4(0));
        require(gate.reservedOf(address(token), address(treasury)) == 1000e6, "left in place");
        vm.prank(executor);
        gate.release(bytes32(uint256(2))); // module now shows it paid
        require(gate.committedOf(address(token), address(treasury)) == 0, "released");
    }

    /// @dev Reserve for request A, then request B tries to spend the committed funds.
    function testFuzzOtherRequestCannotSpendCommittedFunds(uint256 reserved, uint256 spend) external {
        reserved = 8000e6 + (reserved % (1990e6 + 1)); // keeps the spend under the 2000 per-tx limit
        _reserve(1, address(op1), reserved);
        uint256 free = 10000e6 - 10e6 - reserved;
        spend = free + 1 + (spend % (2000e6 - free));
        I.PaymentApproval memory ap = _approval(2, spend);
        bytes memory sig = _sign(ap);
        vm.prank(executor);
        vm.expectRevert(ReserveHoldExecutor.CommittedFundsBreach.selector);
        gate.pay(ap, sig, STEP, spend);
    }
}
