// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;
import {TreasuryFixture} from "../helpers/TreasuryFixture.sol";
import {ITreasuryPilotModule as I} from "../../src/interfaces/ITreasuryPilotModule.sol";
import {TreasuryPilotErrors as E} from "../../src/libraries/TreasuryPilotErrors.sol";

/// @notice Contract portion of source AT cases; off-chain discovery/recovery is not claimed.
contract AcceptanceTest is TreasuryFixture {
    function test_AT01_ApprovedRequestPaysWithCompleteReplayEvidence() external {
        I.PaymentApproval memory ap = _approval(1, 100e6);
        _pay(ap, bytes32(uint256(1)));
        require(module.requestPaid(ap.requestId) && module.fingerprintPaid(ap.fingerprint), "receipt state");
    }

    function test_AT02_InsufficientOperationalCashRefillThenPay() external {
        _safeTx(op1, address(token), abi.encodeWithSignature("transfer(address,uint256)", address(0xD00D), 9980e6));
        I.PaymentApproval memory ap = _approval(1, 100e6);
        _refill(ap, bytes32(uint256(1)), 90e6);
        _pay(ap, bytes32(uint256(2)));
        require(token.balanceOf(address(op1)) == 10e6 && token.balanceOf(vendor) == 100e6, "refill-pay");
    }

    function test_AT05_UnknownPayeeCannotExecute() external {
        I.PaymentApproval memory ap = _approval(1, 1e6);
        ap.payee = address(0xABCD);
        _expectPayError(ap, E.PayeeUnknown.selector);
    }

    function test_AT05_CoolingPayeeCannotExecute() external {
        _owner(abi.encodeCall(module.addPayee, (vendor)));
        _expectPayError(_approval(1, 1e6), E.PayeeCooling.selector);
    }

    function test_AT05_PerRequestAndDailyCapsAreBothEnforced() external {
        _expectPayError(_approval(1, 2000e6 + 1), E.OverPerRequestLimit.selector);
        config.pay.daily = 2000e6;
        _owner(abi.encodeCall(module.configureMandate, (config)));
        _pay(_approval(1, 2000e6), bytes32(uint256(1)));
        _expectPayError(_approval(2, 1), E.OverDailyLimit.selector);
    }

    function test_AT08_ApprovalExpiryPreventsSettlement() external {
        I.PaymentApproval memory ap = _approval(1, 1e6);
        ap.expiry = uint64(block.timestamp - 1);
        _expectPayError(ap, E.ApprovalExpired.selector);
    }

    function test_AT07_PauseAfterRefillPreservesPartialCompletion() external {
        _safeTx(op1, address(token), abi.encodeWithSignature("transfer(address,uint256)", address(0xD00D), 9980e6));
        I.PaymentApproval memory ap = _approval(1, 100e6);
        _refill(ap, bytes32(uint256(1)), 90e6);
        _owner(abi.encodeCall(module.pause, ()));
        _expectPayError(ap, E.NotActive.selector);
        require(module.refilledFor(ap.requestId, address(op1)) && !module.requestPaid(ap.requestId), "partial state");
        _owner(abi.encodeCall(module.resume, ()));
        bytes memory signature = _sign(ap);
        vm.expectRevert(E.AlreadyRefilledForRequest.selector);
        vm.prank(executor);
        module.refill(ap, signature, bytes32(uint256(3)), address(op1), 1);
        _pay(ap, bytes32(uint256(2)));
    }

    function test_AT11_ExactOwnerExceptionDoesNotLiftBuffer() external {
        I.PaymentApproval memory ap = _approval(1, 2500e6);
        _owner(
            abi.encodeCall(
                module.grantException, (ap.requestId, uint128(ap.amount), vendor, uint64(block.timestamp + 1 days))
            )
        );
        _owner(
            abi.encodeCall(
                module.setBuffer, (address(op1), token.balanceOf(address(op1)), token.balanceOf(address(op1)))
            )
        );
        _expectPayError(ap, E.BufferBreach.selector);
        (,,,, bool used) = module.exceptions(ap.requestId);
        require(!used, "failed exception consumed");
    }

    function test_AT06_ReplayedRequestAndDuplicateInvoiceAreRejected() external {
        I.PaymentApproval memory ap = _approval(1, 1e6);
        _pay(ap, bytes32(uint256(1)));
        _expectPayError(ap, E.RequestAlreadyPaid.selector);
        ap.requestId = bytes32(uint256(2));
        _expectPayError(ap, E.DuplicateFingerprint.selector);
    }

    function test_AT10_CompetingPaymentsRecheckCashFloor() external {
        _safeTx(op1, address(token), abi.encodeWithSignature("transfer(address,uint256)", address(0xD00D), 9890e6));
        I.PaymentApproval memory first = _approval(1, 100e6);
        I.PaymentApproval memory second = _approval(2, 100e6);
        bytes memory staleSignature = _sign(second);
        _pay(first, bytes32(uint256(1)));
        vm.expectRevert(E.BufferBreach.selector);
        vm.prank(executor);
        module.pay(second, staleSignature, bytes32(uint256(2)), second.amount);
        require(token.balanceOf(address(op1)) == 10e6 && !module.requestPaid(second.requestId), "competing cash");
    }

    function test_AT12_MinimumRefillPreservesReserveAndLeavesTargetUnmet() external {
        _safeTx(op1, address(token), abi.encodeWithSignature("transfer(address,uint256)", address(0xD00D), 9980e6));
        _owner(abi.encodeCall(module.setBuffer, (address(treasury), 29910e6, 0)));
        I.PaymentApproval memory ap = _approval(1, 100e6);
        _refill(ap, bytes32(uint256(1)), 90e6);
        _pay(ap, bytes32(uint256(2)));
        require(token.balanceOf(address(treasury)) == 29910e6, "reserve");
        require(token.balanceOf(address(op1)) == 10e6 && module.targetOf(address(op1)) == 150e6, "unmet target");
    }
}

