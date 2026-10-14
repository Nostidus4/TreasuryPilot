// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;
import {TreasuryFixture} from "../helpers/TreasuryFixture.sol";
import {TreasuryPilotErrors as E} from "../../src/libraries/TreasuryPilotErrors.sol";
import {ITreasuryPilotModule as I} from "../../src/interfaces/ITreasuryPilotModule.sol";
import {IERC1271} from "@openzeppelin/contracts/interfaces/IERC1271.sol";
import {TestUSDC} from "../../src/test-assets/TestUSDC.sol";

contract ContractApprover is IERC1271 {
    bytes32 public digest;

    function setDigest(bytes32 digest_) external {
        digest = digest_;
    }

    function isValidSignature(bytes32 digest_, bytes memory) external view returns (bytes4) {
        return digest_ == digest ? IERC1271.isValidSignature.selector : bytes4(0xffffffff);
    }
}

contract TreasuryPaymentsTest is TreasuryFixture {
    function testAssetAllowlistAndDailyCountersAreIndependent() external {
        TestUSDC second = new TestUSDC();
        second.mint(address(op1), 1000e6);
        I.MandateInit memory m = config;
        m.pay = I.Limits(100e6, 100e6);
        _owner(abi.encodeCall(module.configureMandate, (m)));
        _owner(abi.encodeWithSignature("setAssetPolicy(address,bool,(uint128,uint128),(uint128,uint128))", address(second), true, I.Limits(100e6, 100e6), I.Limits(0, 0)));
        _owner(abi.encodeWithSignature("setBuffer(address,address,uint256,uint256)", address(second), address(op1), 20e6, 150e6));

        I.PaymentApproval memory primaryFirst = _approval(501, 60e6);
        _pay(primaryFirst, bytes32(uint256(501)));

        I.PaymentApproval memory secondary = _approval(502, 60e6);
        secondary.asset = address(second);
        _pay(secondary, bytes32(uint256(502)));

        I.PaymentApproval memory primaryLast = _approval(503, 40e6);
        _pay(primaryLast, bytes32(uint256(503)));

        require(module.usedToday(module.PAY(), address(token)) == 100e6, "primary counter");
        require(module.usedToday(module.PAY(), address(second)) == 60e6, "secondary counter");
        require(module.remainingToday(module.PAY(), address(token)) == 0, "primary remainder");
        require(module.remainingToday(module.PAY(), address(second)) == 40e6, "secondary remainder");
        require(token.balanceOf(vendor) == 100e6 && second.balanceOf(vendor) == 60e6, "asset transfers");
        require(module.bufferOf(address(token), address(op1)) == 10e6, "primary buffer unchanged");
        require(module.bufferOf(address(second), address(op1)) == 20e6, "secondary buffer");
    }

    function testPaymentApprovalRejectsAssetOutsideAllowlist() external {
        TestUSDC second = new TestUSDC();
        I.PaymentApproval memory ap = _approval(504, 1e6);
        ap.asset = address(second);
        bytes memory sig = _sign(ap);
        vm.expectRevert(E.ApprovalInvalid.selector);
        module.verifyApproval(ap, sig);
    }
    function testPayTransfersExactApprovedAmountAndSetsReplayState() external {
        I.PaymentApproval memory ap = _approval(1, 100e6);
        uint256 beforeBalance = token.balanceOf(address(op1));
        _pay(ap, bytes32(uint256(1)));
        require(
            token.balanceOf(vendor) == 100e6 && token.balanceOf(address(op1)) == beforeBalance - 100e6, "exact transfer"
        );
        require(
            module.requestPaid(ap.requestId) && module.stepUsed(bytes32(uint256(1)))
                && module.fingerprintPaid(ap.fingerprint),
            "replay state"
        );
        _expectPayError(ap, E.RequestAlreadyPaid.selector);
        I.PaymentApproval memory second = _approval(2, 1e6);
        bytes memory sig = _sign(second);
        vm.expectRevert(E.StepAlreadyExecuted.selector);
        vm.prank(executor);
        module.pay(second, sig, bytes32(uint256(1)));
    }

    function testPayOnlyOperationalWalletAndExecutor() external {
        I.PaymentApproval memory ap = _approval(1, 100e6);
        ap.payingWallet = address(treasury);
        _expectPayError(ap, E.NotOperationalWallet.selector);
        ap.payingWallet = address(op1);
        bytes memory sig = _sign(ap);
        vm.expectRevert(E.NotExecutor.selector);
        module.pay(ap, sig, bytes32(uint256(1)));
    }

    function testChangedFieldWrongChainWrongTreasuryAndMalformedSignatureAreRejected() external {
        I.PaymentApproval memory ap = _approval(1, 100e6);
        bytes memory sig = _sign(ap);
        ap.amount += 1;
        vm.expectRevert(E.ApprovalInvalid.selector);
        module.verifyApproval(ap, sig);
        ap.amount -= 1;
        vm.chainId(block.chainid + 1);
        vm.expectRevert(E.ApprovalInvalid.selector);
        module.verifyApproval(ap, sig);
        ap.treasury = address(implementation);
        vm.expectRevert(E.ApprovalInvalid.selector);
        module.verifyApproval(ap, sig);
        ap.treasury = address(module);
        vm.expectRevert(E.ApprovalInvalid.selector);
        module.verifyApproval(ap, hex"00");
    }

    function testRemovedApproverAndExpiredApprovalHaveDistinctErrors() external {
        I.PaymentApproval memory ap = _approval(1, 1e6);
        bytes memory sig = _sign(ap);
        address[] memory add = new address[](1);
        add[0] = address(0xA22);
        address[] memory remove = new address[](1);
        remove[0] = approver;
        _owner(abi.encodeCall(module.setApprovers, (add, remove)));
        vm.expectRevert(E.NotApprover.selector);
        module.verifyApproval(ap, sig);
        vm.warp(uint256(ap.expiry) + 1);
        vm.expectRevert(E.ApprovalExpired.selector);
        module.verifyApproval(ap, sig);
    }

    function testERC1271ApproverSupportsNonEOASignatureLength() external {
        ContractApprover contractApprover = new ContractApprover();
        address[] memory add = new address[](1);
        add[0] = address(contractApprover);
        address[] memory empty = new address[](0);
        _owner(abi.encodeCall(module.setApprovers, (add, empty)));
        I.PaymentApproval memory ap = _approval(1, 1e6);
        contractApprover.setDigest(module.hashApproval(ap));
        bytes memory sig = abi.encode(address(contractApprover), hex"123456");
        vm.prank(executor);
        module.pay(ap, sig, bytes32(uint256(1)));
        require(module.requestPaid(ap.requestId), "contract approver");
    }

    function testExpiredMandateAndFutureWindowRejectExecutor() external {
        vm.warp(uint256(config.expiresAt) + 1);
        _expectPayError(_approval(1, 1e6), E.MandateExpired.selector);
        vm.warp(uint256(config.validFrom) - 1);
        _expectPayError(_approval(1, 1e6), E.MandateExpired.selector);
    }

    function testEarlyAmountAtBoundaryAndStandardOneSecondLater() external {
        I.PaymentApproval memory ap = _approval(1, 100e6);
        ap.earlyAmount = 90e6;
        ap.earlyPayBy = uint64(block.timestamp);
        _pay(ap, bytes32(uint256(1)));
        require(token.balanceOf(vendor) == 90e6 && module.usedToday(module.PAY()) == 90e6, "early amount");
        ap.requestId = bytes32(uint256(2));
        ap.fingerprint = bytes32(uint256(2));
        vm.warp(block.timestamp + 1);
        _pay(ap, bytes32(uint256(2)));
        require(token.balanceOf(vendor) == 190e6 && module.usedToday(module.PAY()) == 190e6, "standard amount");
        ap = _approval(3, 100e6);
        ap.earlyAmount = 100e6 + 1;
        _expectPayError(ap, E.WrongPaymentOption.selector);
    }

    function testDailyBudgetSharedAcrossOperationalSafesAndUTCReset() external {
        config.pay = I.Limits(100e6, 150e6);
        _owner(abi.encodeCall(module.configureMandate, (config)));
        _pay(_approval(1, 100e6), bytes32(uint256(1)));
        I.PaymentApproval memory ap = _approval(2, 51e6);
        ap.payingWallet = address(op2);
        _expectPayError(ap, E.OverDailyLimit.selector);
        ap.amount = 50e6;
        _pay(ap, bytes32(uint256(2)));
        require(module.usedToday(module.PAY()) == 150e6, "daily aggregate");
        vm.warp((block.timestamp / 1 days + 1) * 1 days);
        require(module.usedToday(module.PAY()) == 0, "UTC reset");
        _pay(_approval(3, 100e6), bytes32(uint256(3)));
    }

    function testBufferBoundaryAndPerRequestLimit() external {
        uint256 balance = token.balanceOf(address(op1));
        _owner(abi.encodeCall(module.setBuffer, (address(op1), balance - 100e6, balance)));
        _expectPayError(_approval(1, 100e6 + 1), E.BufferBreach.selector);
        _pay(_approval(1, 100e6), bytes32(uint256(1)));
        require(token.balanceOf(address(op1)) == module.bufferOf(address(op1)), "exact floor");
        _expectPayError(_approval(2, 2000e6 + 1), E.OverPerRequestLimit.selector);
    }

    function testRefillTargetReplayBoundFloorAndIndependentBudget() external {
        // Drain through an owner Safe transaction; executor remains constrained.
        _safeTx(op1, address(token), abi.encodeWithSignature("transfer(address,uint256)", vendor, 9980e6));
        I.PaymentApproval memory ap = _approval(1, 100e6);
        bytes memory sig = _sign(ap);
        vm.expectRevert(E.WrongRefillTarget.selector);
        vm.prank(executor);
        module.refill(ap, sig, bytes32(uint256(1)), address(op2), 1e6);
        vm.expectRevert(E.RefillExceedsNeed.selector);
        vm.prank(executor);
        module.refill(ap, sig, bytes32(uint256(1)), address(op1), 230e6 + 1);
        _refill(ap, bytes32(uint256(1)), 230e6);
        require(token.balanceOf(address(op1)) == 250e6 && module.usedToday(module.PAY()) == 0, "refill bound");
        vm.expectRevert(E.AlreadyRefilledForRequest.selector);
        vm.prank(executor);
        module.refill(ap, sig, bytes32(uint256(2)), address(op1), 1);
        require(module.usedToday(module.REFILL()) == 230e6, "refill counter");
        _owner(abi.encodeCall(module.setBuffer, (address(treasury), token.balanceOf(address(treasury)), 0)));
        ap = _approval(2, 100e6);
        sig = _sign(ap);
        vm.expectRevert(E.SourceBufferBreach.selector);
        vm.prank(executor);
        module.refill(ap, sig, bytes32(uint256(3)), address(op1), 1);
    }

    function testExceptionMatchesOnceAndNeverLiftsDailyCap() external {
        _owner(
            abi.encodeCall(
                module.grantException, (bytes32(uint256(1)), uint128(2500e6), vendor, uint64(block.timestamp + 1 days))
            )
        );
        _pay(_approval(1, 2500e6), bytes32(uint256(1)));
        (,,,, bool used) = module.exceptions(bytes32(uint256(1)));
        require(used, "exception not consumed");
        _expectPayError(_approval(1, 2500e6), E.RequestAlreadyPaid.selector);
        _owner(
            abi.encodeCall(
                module.grantException, (bytes32(uint256(2)), uint128(2500e6), vendor, uint64(block.timestamp + 1 days))
            )
        );
        _expectPayError(_approval(2, 2600e6), E.ExceptionInvalid.selector);
        config.pay.daily = 3000e6;
        _owner(abi.encodeCall(module.configureMandate, (config)));
        _expectPayError(_approval(2, 2500e6), E.ExceptionInvalid.selector);
        _owner(
            abi.encodeCall(
                module.grantException, (bytes32(uint256(2)), uint128(2500e6), vendor, uint64(block.timestamp + 1 days))
            )
        );
        _expectPayError(_approval(2, 2500e6), E.OverDailyLimit.selector);
        (,,,, used) = module.exceptions(bytes32(uint256(2)));
        require(!used, "reverted exception consumed");
    }

    function testDuplicateFingerprintNeedsOwnerGrantForExactNewRequest() external {
        I.PaymentApproval memory first = _approval(1, 1e6);
        _pay(first, bytes32(uint256(1)));
        I.PaymentApproval memory second = _approval(2, 1e6);
        second.fingerprint = first.fingerprint;
        _expectPayError(second, E.DuplicateFingerprint.selector);
        _owner(abi.encodeCall(module.allowDuplicate, (first.fingerprint, second.requestId)));
        I.PaymentApproval memory other = _approval(3, 1e6);
        other.fingerprint = first.fingerprint;
        _expectPayError(other, E.DuplicateFingerprint.selector);
        _pay(second, bytes32(uint256(2)));
        require(module.duplicateAllowedFor(first.fingerprint) == bytes32(0), "duplicate grant not consumed");
        _expectPayError(other, E.DuplicateFingerprint.selector);
    }

    function testFuzzEarlyPaymentOption(uint64 amountSeed, uint64 earlySeed, bool afterDate) external {
        uint256 amount = uint256(amountSeed) % 2000e6 + 1;
        uint256 early = uint256(earlySeed) % (amount + 1);
        I.PaymentApproval memory ap = _approval(1, amount);
        ap.earlyAmount = early;
        ap.earlyPayBy = uint64(block.timestamp);
        if (afterDate) vm.warp(block.timestamp + 1);
        _pay(ap, bytes32(uint256(1)));
        uint256 expected = early > 0 && !afterDate ? early : amount;
        require(token.balanceOf(vendor) == expected && module.usedToday(module.PAY()) == expected, "payment option");
    }
}
