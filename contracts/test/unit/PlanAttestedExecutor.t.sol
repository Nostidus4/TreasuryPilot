// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;
import {TreasuryFixture} from "../helpers/TreasuryFixture.sol";
import {PlanAttestedExecutor} from "../../src/PlanAttestedExecutor.sol";
import {PlanAttestationHash as H} from "../../src/libraries/PlanAttestationHash.sol";
import {TreasuryPilotErrors as E} from "../../src/libraries/TreasuryPilotErrors.sol";
import {ITreasuryPilotModule as I} from "../../src/interfaces/ITreasuryPilotModule.sol";

contract PlanAttestedExecutorTest is TreasuryFixture {
    uint256 internal constant POLICY_KEY = 8; // public synthetic fixture identity, as in the vectors
    PlanAttestedExecutor internal gate;
    bytes32 internal constant REFILL_STEP = keccak256("refill step");
    bytes32 internal constant PAY_STEP = keccak256("pay step");

    function setUp() public override {
        super.setUp();
        gate = new PlanAttestedExecutor(module, executor, vm.addr(POLICY_KEY));
        I.MandateInit memory m = config;
        m.executor = address(gate);
        m.validFrom = uint64(block.timestamp - 300);
        _owner(abi.encodeCall(module.configureMandate, (m)));
    }

    function _att(I.PaymentApproval memory ap, uint256 nonce) internal view returns (H.PlanAttestation memory att) {
        bytes32[] memory steps = new bytes32[](2);
        steps[0] = REFILL_STEP;
        steps[1] = PAY_STEP;
        uint256[] memory amounts = new uint256[](2);
        amounts[0] = ap.amount;
        amounts[1] = ap.earlyAmount > 0 && block.timestamp <= ap.earlyPayBy ? ap.earlyAmount : ap.amount;
        att = H.PlanAttestation(
            keccak256(abi.encode("plan", ap.requestId)),
            ap.requestId,
            steps,
            amounts,
            keccak256("policy v1"),
            executor,
            uint64(block.timestamp + 15 minutes),
            nonce,
            keccak256("evidence")
        );
    }

    function _sign(H.PlanAttestation memory att) internal view returns (bytes memory) {
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(POLICY_KEY, H.digest(att, address(module)));
        return abi.encodePacked(r, s, v);
    }

    function _gatePay(I.PaymentApproval memory ap, H.PlanAttestation memory att, bytes memory sig) internal {
        _gatePay(ap, att, sig, bytes4(0));
    }

    function _gatePay(I.PaymentApproval memory ap, H.PlanAttestation memory att, bytes memory sig, bytes4 err)
        internal
    {
        bytes memory approverSig = _sign(ap);
        uint256 amount = ap.earlyAmount > 0 && block.timestamp <= ap.earlyPayBy ? ap.earlyAmount : ap.amount;
        if (err != bytes4(0)) vm.expectRevert(err);
        vm.prank(executor);
        gate.pay(ap, approverSig, PAY_STEP, amount, att, sig);
    }

    function testSteppedPlanSharesOneAttestation() external {
        vm.prank(address(op1));
        token.transfer(address(1), 9990e6);
        I.PaymentApproval memory ap = _approval(901, 100e6);
        H.PlanAttestation memory att = _att(ap, 1);
        bytes memory sig = _sign(att);
        bytes memory approverSig = _sign(ap);
        vm.startPrank(executor);
        gate.refill(ap, approverSig, REFILL_STEP, address(treasury), address(op1), 100e6, att, sig);
        gate.pay(ap, approverSig, PAY_STEP, ap.amount, att, sig);
        vm.stopPrank();
        require(token.balanceOf(vendor) == 100e6, "paid");
        require(gate.nonceBoundTo(1) == att.planHash, "nonce bound");
    }

    function testAttestedExecutorPaysFreshQuoteAmountWithinSignedMaximum() external {
        I.PaymentApproval memory ap = _approval(914, 100e6);
        ap.isFiat = true;
        H.PlanAttestation memory att = _att(ap, 15);
        att.stepAmounts[1] = 75e6;
        bytes memory attSig = _sign(att);
        bytes memory approverSig = _sign(ap);

        vm.prank(executor);
        gate.pay(ap, approverSig, PAY_STEP, 75e6, att, attSig);

        require(token.balanceOf(vendor) == 75e6, "fresh quote amount not paid");
        require(module.usedToday(module.PAY(), address(token)) == 75e6, "counter not updated by actual amount");
    }

    function testAttestedExecutorRejectsFreshQuoteAboveSignedMaximum() external {
        I.PaymentApproval memory ap = _approval(915, 100e6);
        ap.isFiat = true;
        H.PlanAttestation memory att = _att(ap, 16);
        att.stepAmounts[1] = 101e6;
        bytes memory attSig = _sign(att);
        bytes memory approverSig = _sign(ap);

        vm.expectRevert(E.WrongPaymentOption.selector);
        vm.prank(executor);
        gate.pay(ap, approverSig, PAY_STEP, 101e6, att, attSig);

        require(token.balanceOf(vendor) == 0, "over-cap payment was transferred");
    }

    function testAttestedAmountMustMatchTheSubmittedAmount() external {
        I.PaymentApproval memory ap = _approval(916, 100e6);
        ap.isFiat = true;
        H.PlanAttestation memory att = _att(ap, 17);
        att.stepAmounts[1] = 75e6;
        bytes memory attSig = _sign(att);
        bytes memory approverSig = _sign(ap);

        vm.expectRevert(E.AttestationInvalid.selector);
        vm.prank(executor);
        gate.pay(ap, approverSig, PAY_STEP, 76e6, att, attSig);
        require(token.balanceOf(vendor) == 0, "unattested amount was transferred");
    }

    function testAttestationNeedsOneAmountPerStep() external {
        I.PaymentApproval memory ap = _approval(917, 100e6);
        H.PlanAttestation memory att = _att(ap, 18);
        att.stepAmounts = new uint256[](1);
        _gatePay(ap, att, _sign(att), E.AttestationInvalid.selector);
    }

    function testDirectExecutorCallsNoLongerBypassTheGate() external {
        I.PaymentApproval memory ap = _approval(902, 100e6);
        bytes memory approverSig = _sign(ap);
        vm.expectRevert(E.NotExecutor.selector);
        vm.prank(executor);
        module.pay(ap, approverSig, PAY_STEP, ap.amount);
    }

    function testExpiredAttestationReverts() external {
        I.PaymentApproval memory ap = _approval(903, 100e6);
        H.PlanAttestation memory att = _att(ap, 2);
        bytes memory sig = _sign(att);
        vm.warp(att.validUntil + 1);
        ap.expiry = uint64(block.timestamp + 1 days);
        _gatePay(ap, att, sig, E.AttestationExpired.selector);
    }

    function testWrongSignerReverts() external {
        I.PaymentApproval memory ap = _approval(904, 100e6);
        H.PlanAttestation memory att = _att(ap, 3);
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(9, H.digest(att, address(module)));
        _gatePay(ap, att, abi.encodePacked(r, s, v), E.AttestationInvalid.selector);
    }

    function testAlteredAttestationReverts() external {
        I.PaymentApproval memory ap = _approval(905, 100e6);
        H.PlanAttestation memory att = _att(ap, 4);
        bytes memory sig = _sign(att);
        att.stepIds[1] = keccak256("another step");
        _gatePay(ap, att, sig, E.AttestationInvalid.selector);
    }

    function testStepOutsideThePlanReverts() external {
        I.PaymentApproval memory ap = _approval(906, 100e6);
        H.PlanAttestation memory att = _att(ap, 5);
        att.stepIds[1] = keccak256("another step");
        bytes memory sig = _sign(att);
        _gatePay(ap, att, sig, E.AttestationInvalid.selector);
    }

    function testAttestationForAnotherRequestReverts() external {
        I.PaymentApproval memory ap = _approval(907, 100e6);
        H.PlanAttestation memory att = _att(_approval(908, 1), 6);
        bytes memory sig = _sign(att);
        _gatePay(ap, att, sig, E.AttestationInvalid.selector);
    }

    function testAttestationForAnotherExecutorReverts() external {
        I.PaymentApproval memory ap = _approval(909, 100e6);
        H.PlanAttestation memory att = _att(ap, 7);
        att.executor = address(0xBAD);
        bytes memory sig = _sign(att);
        _gatePay(ap, att, sig, E.AttestationInvalid.selector);
    }

    function testAttestationForAnotherTreasuryReverts() external {
        I.PaymentApproval memory ap = _approval(910, 100e6);
        H.PlanAttestation memory att = _att(ap, 8);
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(POLICY_KEY, H.digest(att, address(0x1234)));
        _gatePay(ap, att, abi.encodePacked(r, s, v), E.AttestationInvalid.selector);
    }

    function testNonceCannotBeReusedForAnotherPlan() external {
        I.PaymentApproval memory first = _approval(911, 10e6);
        H.PlanAttestation memory att = _att(first, 9);
        _gatePay(first, att, _sign(att));
        I.PaymentApproval memory second = _approval(912, 10e6);
        H.PlanAttestation memory other = _att(second, 9);
        bytes memory sig = _sign(other);
        _gatePay(second, other, sig, E.NonceReused.selector);
    }

    function testOnlyOperatorCanUseTheGate() external {
        I.PaymentApproval memory ap = _approval(913, 100e6);
        H.PlanAttestation memory att = _att(ap, 10);
        bytes memory sig = _sign(att);
        bytes memory approverSig = _sign(ap);
        vm.expectRevert(E.NotExecutor.selector);
        gate.pay(ap, approverSig, PAY_STEP, ap.amount, att, sig);
        vm.expectRevert(E.NotExecutor.selector);
        gate.borrow(bytes32(uint256(1)));
    }

    function testLiquidityStepsNeedAnAttestationToo() external {
        bytes32 stepId = keccak256("supply step");
        I.PaymentApproval memory ap = _approval(0, 0);
        ap.requestId = bytes32(0);
        H.PlanAttestation memory att = _att(ap, 11);
        att.stepIds = new bytes32[](1);
        att.stepIds[0] = stepId;
        att.stepAmounts = new uint256[](1);
        att.stepAmounts[0] = 100e6;
        bytes memory sig = _sign(att);
        vm.prank(executor);
        gate.supply(bytes32(0), stepId, 100e6, att, sig);
        require(module.stepUsed(stepId), "supplied");
        att.stepIds[0] = keccak256("different");
        vm.expectRevert(E.AttestationInvalid.selector);
        vm.prank(executor);
        gate.withdraw(bytes32(0), stepId, 1e6, att, sig);
    }
}
