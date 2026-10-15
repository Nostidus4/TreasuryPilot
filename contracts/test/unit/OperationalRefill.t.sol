// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;
import {TreasuryFixture} from "../helpers/TreasuryFixture.sol";
import {TreasuryPilotErrors as E} from "../../src/libraries/TreasuryPilotErrors.sol";
import {ITreasuryPilotModule as I} from "../../src/interfaces/ITreasuryPilotModule.sol";

/// SC-L06: O2 may fund O1 when Safe T allowed the path; the source keeps its own buffer.
contract OperationalRefillTest is TreasuryFixture {
    bytes32 internal constant STEP = bytes32(uint256(1));

    function setUp() public override {
        super.setUp();
        _safeTx(op1, address(token), abi.encodeWithSignature("transfer(address,uint256)", vendor, 9980e6));
    }

    function _from(I.PaymentApproval memory ap, address from, uint256 amount) internal {
        bytes memory sig = _sign(ap);
        vm.prank(executor);
        module.refill(ap, sig, STEP, from, ap.payingWallet, amount);
    }

    function _expectFrom(I.PaymentApproval memory ap, address from, uint256 amount, bytes4 err) internal {
        bytes memory sig = _sign(ap);
        vm.expectRevert(err);
        vm.prank(executor);
        module.refill(ap, sig, STEP, from, ap.payingWallet, amount);
    }

    function testMandatedOperationalRefillSucceeds() external {
        _owner(abi.encodeCall(module.setRefillPath, (address(op2), address(op1), true)));
        uint256 t = token.balanceOf(address(treasury));
        _from(_approval(1, 100e6), address(op2), 230e6);
        require(token.balanceOf(address(op1)) == 250e6, "target funded");
        require(token.balanceOf(address(op2)) == 10000e6 - 230e6, "source debited");
        require(token.balanceOf(address(treasury)) == t, "T untouched");
        require(module.usedToday(module.REFILL(), address(token)) == 230e6, "refill counter");
    }

    function testPathNotAllowedAndDirectional() external {
        _expectFrom(_approval(1, 100e6), address(op2), 1e6, E.RefillPathNotAllowed.selector);
        _owner(abi.encodeCall(module.setRefillPath, (address(op1), address(op2), true)));
        _expectFrom(_approval(1, 100e6), address(op2), 1e6, E.RefillPathNotAllowed.selector);
        _owner(abi.encodeCall(module.setRefillPath, (address(op2), address(op1), true)));
        _owner(abi.encodeCall(module.setRefillPath, (address(op2), address(op1), false)));
        _expectFrom(_approval(1, 100e6), address(op2), 1e6, E.RefillPathNotAllowed.selector);
    }

    function testSelfRefillRejected() external {
        _expectFrom(_approval(1, 100e6), address(op1), 1e6, E.RefillPathNotAllowed.selector);
        vm.expectRevert(E.InvalidConfiguration.selector);
        vm.prank(address(treasury));
        module.setRefillPath(address(op1), address(op1), true);
    }

    function testSourceBufferBreachRejected() external {
        _owner(abi.encodeCall(module.setRefillPath, (address(op2), address(op1), true)));
        _safeTx(op2, address(token), abi.encodeWithSignature("transfer(address,uint256)", vendor, 9980e6));
        // op2 holds 20 with a buffer of 10, so 11 breaches and 10 does not.
        _expectFrom(_approval(1, 100e6), address(op2), 11e6, E.SourceBufferBreach.selector);
        _from(_approval(1, 100e6), address(op2), 10e6);
        require(token.balanceOf(address(op2)) == 10e6, "buffer kept");
    }

    function testPathAdminIsOwnerOnlyAndOperationalOnly() external {
        vm.expectRevert(E.NotOwner.selector);
        module.setRefillPath(address(op2), address(op1), true);
        vm.expectRevert(E.InvalidConfiguration.selector);
        vm.prank(address(treasury));
        module.setRefillPath(address(treasury), address(op1), true);
    }

    function testStillOnePerRequestAcrossSources() external {
        _owner(abi.encodeCall(module.setRefillPath, (address(op2), address(op1), true)));
        _from(_approval(1, 100e6), address(op2), 10e6);
        bytes memory sig = _sign(_approval(1, 100e6));
        vm.expectRevert(E.AlreadyRefilledForRequest.selector);
        vm.prank(executor);
        module.refill(_approval(1, 100e6), sig, bytes32(uint256(2)), address(treasury), address(op1), 1e6);
    }
}
