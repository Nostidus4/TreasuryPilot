// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;
import {TreasuryFixture} from "../helpers/TreasuryFixture.sol";
import {ITreasuryPilotModule as I} from "../../src/interfaces/ITreasuryPilotModule.sol";
import {TreasuryPilotErrors as E} from "../../src/libraries/TreasuryPilotErrors.sol";

contract DirectCallBypassTest is TreasuryFixture {
    function testDirectAlteredPayeeAmountAssetAndRequestFailCryptographicProof() external {
        I.PaymentApproval memory ap = _approval(1, 100e6);
        bytes memory sig = _sign(ap);
        ap.payee = address(0xBAD);
        _expectInvalid(ap, sig);
        ap.payee = vendor;
        ap.amount += 1;
        _expectInvalid(ap, sig);
        ap.amount -= 1;
        ap.asset = vendor;
        _expectInvalid(ap, sig);
        ap.asset = address(token);
        ap.requestId = bytes32(uint256(2));
        _expectInvalid(ap, sig);
    }

    function testDirectUnsignedApprovalCannotMoveTreasuryFunds() external {
        I.PaymentApproval memory ap = _approval(1, 100e6);
        vm.expectRevert(E.ApprovalInvalid.selector);
        vm.prank(executor);
        module.pay(ap, abi.encode(approver, bytes("")), bytes32(uint256(1)));
        require(module.usedToday(module.PAY()) == 0 && !module.requestPaid(ap.requestId), "unauthorized state");
    }

    function testDirectRandomCallerCannotPayRefillSupplyWithdrawBorrowRepayOrGovern() external {
        I.PaymentApproval memory ap = _approval(1, 1e6);
        bytes memory sig = _sign(ap);
        vm.expectRevert(E.NotExecutor.selector);
        module.pay(ap, sig, bytes32(uint256(1)));
        vm.expectRevert(E.NotExecutor.selector);
        module.refill(ap, sig, bytes32(uint256(1)), address(op1), 1);
        vm.expectRevert(E.NotExecutor.selector);
        module.supply(bytes32(uint256(1)), 1);
        vm.expectRevert(E.NotExecutor.selector);
        module.withdraw(bytes32(uint256(1)), 1);
        vm.expectRevert(E.NotExecutor.selector);
        module.borrow(bytes32(uint256(1)));
        vm.expectRevert(E.NotExecutor.selector);
        module.repay(bytes32(uint256(1)));
        vm.expectRevert(E.NotOwner.selector);
        module.grantException(ap.requestId, 1, vendor, uint64(block.timestamp + 1));
        vm.expectRevert(E.NotOwner.selector);
        module.allowDuplicate(ap.fingerprint, ap.requestId);
        vm.expectRevert(E.NotGuardianOrOwner.selector);
        module.pause();
    }

    function testDirectPausedCoolingDailyLimitAndCancelledRequestsRevertDocumentedErrors() external {
        _owner(abi.encodeCall(module.pause, ()));
        _expectPayError(_approval(1, 1), E.NotActive.selector);
        _owner(abi.encodeCall(module.resume, ()));
        _owner(abi.encodeCall(module.addPayee, (vendor)));
        _expectPayError(_approval(1, 1), E.PayeeCooling.selector);
        vm.warp(block.timestamp + config.payeeCoolingSeconds);
        config.pay = I.Limits(1, 1);
        _owner(abi.encodeCall(module.configureMandate, (config)));
        _pay(_approval(1, 1), bytes32(uint256(1)));
        _expectPayError(_approval(2, 1), E.OverDailyLimit.selector);
        vm.prank(approver);
        module.cancelRequest(bytes32(uint256(3)));
        _expectPayError(_approval(3, 1), E.RequestCancelled.selector);
    }

    function testDirectRefillCannotChangeApprovedDestinationOrSpendAboveSourceFloor() external {
        I.PaymentApproval memory ap = _approval(1, 1e6);
        bytes memory sig = _sign(ap);
        vm.expectRevert(E.WrongRefillTarget.selector);
        vm.prank(executor);
        module.refill(ap, sig, bytes32(uint256(1)), vendor, 1);
        _owner(abi.encodeCall(module.setBuffer, (address(treasury), token.balanceOf(address(treasury)), 0)));
        vm.expectRevert(E.SourceBufferBreach.selector);
        vm.prank(executor);
        module.refill(ap, sig, bytes32(uint256(1)), address(op1), 1);
    }

    function testFuzzAnyOneOf13SignedFieldsCannotBeMutated(uint8 selector, uint256 mutation) external {
        vm.assume(mutation != 0);
        I.PaymentApproval memory ap = _approval(1, 100e6);
        bytes memory sig = _sign(ap);
        uint256 field = uint256(selector) % 13;
        // All fields are static ABI words; preserve the uint64/address canonical widths.
        if (field == 3 || field == 4 || field == 5 || field == 6) mutation = mutation % type(uint160).max + 1;
        if (field == 9 || field == 10 || field == 12) mutation = mutation % type(uint64).max + 1;
        assembly ("memory-safe") {
            let location := add(ap, mul(field, 32))
            mstore(location, xor(mload(location), mutation))
        }
        // Mutated expiry / option / treasury can fail a semantic check first; no mutation may pass.
        (bool ok,) = address(module).staticcall(abi.encodeCall(module.verifyApproval, (ap, sig)));
        require(!ok, "unsigned field mutation accepted");
    }

    function _expectInvalid(I.PaymentApproval memory ap, bytes memory sig) internal {
        vm.expectRevert(E.ApprovalInvalid.selector);
        vm.prank(executor);
        module.pay(ap, sig, bytes32(uint256(1)));
    }
}
