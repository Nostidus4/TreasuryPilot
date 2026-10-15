// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;
import {TreasuryFixture} from "../helpers/TreasuryFixture.sol";
import {ThresholdApprovalExecutor as T} from "../../src/ThresholdApprovalExecutor.sol";
import {TreasuryPilotErrors as E} from "../../src/libraries/TreasuryPilotErrors.sol";
import {ITreasuryPilotModule as I} from "../../src/interfaces/ITreasuryPilotModule.sol";

contract ThresholdApprovalExecutorTest is TreasuryFixture {
    T internal gate;
    uint256 internal constant K2 = 8;
    uint256 internal constant K3 = 9;

    function setUp() public override {
        super.setUp();
        gate = new T(module, executor);
        I.MandateInit memory m = config;
        m.executor = address(gate);
        m.validFrom = uint64(block.timestamp - 300);
        _owner(abi.encodeCall(module.configureMandate, (m)));
        address[] memory add = new address[](2);
        add[0] = vm.addr(K2);
        add[1] = vm.addr(K3);
        _owner(abi.encodeCall(module.setApprovers, (add, new address[](0))));
        // <=100 USDC: 1 approver, <=1000: 2, above: 3
        T.Band[] memory b = new T.Band[](3);
        b[0] = T.Band(100e6, 1);
        b[1] = T.Band(1000e6, 2);
        b[2] = T.Band(type(uint128).max, 3);
        _setBands(b);
    }

    function _setBands(T.Band[] memory b) internal {
        _safeTx(treasury, address(gate), abi.encodeCall(gate.setBands, (b)));
    }

    function _sigBy(uint256 key, I.PaymentApproval memory ap) internal view returns (bytes memory) {
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(key, module.hashApproval(ap));
        return abi.encode(vm.addr(key), abi.encodePacked(r, s, v));
    }

    function _pay(I.PaymentApproval memory ap, bytes[] memory sigs, bytes memory err) internal {
        if (err.length > 0) vm.expectRevert(err);
        vm.prank(executor);
        gate.pay(ap, sigs, ap.requestId, ap.amount);
    }

    function _sigs(uint256 n, I.PaymentApproval memory ap) internal view returns (bytes[] memory s) {
        uint256[3] memory keys = [APPROVER_KEY, K2, K3];
        s = new bytes[](n);
        for (uint256 i; i < n; ++i) {
            s[i] = _sigBy(keys[i], ap);
        }
    }

    /// Band matrix: amount at/below each bound needs exactly its k; one fewer signer fails, k passes.
    function testBandMatrix() external {
        uint256[6] memory amounts = [uint256(1e6), 100e6, 100e6 + 1, 1000e6, 1000e6 + 1, 1500e6];
        uint256[6] memory ks = [uint256(1), 1, 2, 2, 3, 3];
        for (uint256 i; i < amounts.length; ++i) {
            I.PaymentApproval memory ap = _approval(100 + i, amounts[i]);
            require(gate.requiredApprovals(amounts[i]) == ks[i], "k");
            if (ks[i] > 1) {
                _pay(
                    ap, _sigs(ks[i] - 1, ap), abi.encodeWithSelector(T.InsufficientApprovals.selector, ks[i] - 1, ks[i])
                );
            }
            _pay(ap, _sigs(ks[i], ap), "");
            require(module.requestPaid(ap.requestId), "paid");
        }
    }

    function testDuplicateSignerCountedOnce() external {
        I.PaymentApproval memory ap = _approval(200, 500e6);
        bytes[] memory s = new bytes[](2);
        s[0] = _sigBy(APPROVER_KEY, ap);
        s[1] = s[0];
        _pay(ap, s, abi.encodeWithSelector(T.InsufficientApprovals.selector, 1, 2));
        // a third copy plus one distinct signer still counts two
        bytes[] memory t = new bytes[](3);
        t[0] = s[0];
        t[1] = s[0];
        t[2] = _sigBy(K2, ap);
        _pay(ap, t, "");
    }

    function testNonApproverSignatureRejected() external {
        I.PaymentApproval memory ap = _approval(201, 500e6);
        bytes[] memory s = new bytes[](2);
        s[0] = _sigBy(APPROVER_KEY, ap);
        s[1] = _sigBy(77, ap);
        _pay(ap, s, abi.encodeWithSelector(E.NotApprover.selector));
    }

    function testSignatureOverDifferentDataRejected() external {
        I.PaymentApproval memory ap = _approval(202, 500e6);
        I.PaymentApproval memory other = _approval(203, 500e6);
        bytes[] memory s = new bytes[](2);
        s[0] = _sigBy(APPROVER_KEY, ap);
        s[1] = _sigBy(K2, other);
        _pay(ap, s, abi.encodeWithSelector(E.ApprovalInvalid.selector));
    }

    function testNoSignaturesAndOnlyOperator() external {
        I.PaymentApproval memory ap = _approval(204, 50e6);
        _pay(ap, new bytes[](0), abi.encodeWithSelector(T.InsufficientApprovals.selector, 0, 1));
        bytes[] memory s = _sigs(1, ap);
        vm.expectRevert(E.NotExecutor.selector);
        gate.pay(ap, s, keccak256("step"), ap.amount);
    }

    function testBandsUnsetAndOwnerOnlyAndValidation() external {
        T fresh = new T(module, executor);
        vm.expectRevert(T.BandsNotSet.selector);
        fresh.requiredApprovals(1);
        T.Band[] memory b = new T.Band[](1);
        b[0] = T.Band(type(uint128).max, 1);
        vm.expectRevert(T.NotOwner.selector);
        fresh.setBands(b);

        T.Band[] memory bad = new T.Band[](2);
        bad[0] = T.Band(100e6, 2);
        bad[1] = T.Band(type(uint128).max, 1); // k decreases
        _expectBadBands(bad);
        bad[1] = T.Band(100e6, 3); // not increasing, not unbounded
        _expectBadBands(bad);
        bad[1] = T.Band(type(uint128).max, 0);
        _expectBadBands(bad);
        _expectBadBands(new T.Band[](0));
    }

    function _expectBadBands(T.Band[] memory b) internal {
        // Safe swallows reverts as a failed inner call, so call as the owner directly.
        vm.expectRevert(T.InvalidBands.selector);
        vm.prank(address(treasury));
        gate.setBands(b);
    }

    /// Fuzz: payment succeeds iff distinct signers >= the band's k.
    function testFuzzDistinctSignersVsBand(uint256 amountSeed, uint8 count, uint8 pick) external {
        uint256 amount = 1 + amountSeed % 5000e6;
        I.PaymentApproval memory ap = _approval(300, amount);
        uint256 n = 1 + uint256(count) % 6;
        uint256[3] memory keys = [APPROVER_KEY, K2, K3];
        bytes[] memory s = new bytes[](n);
        bool[3] memory used;
        uint256 distinct;
        for (uint256 i; i < n; ++i) {
            uint256 idx = uint256(keccak256(abi.encode(pick, i))) % 3;
            if (!used[idx]) {
                used[idx] = true;
                ++distinct;
            }
            s[i] = _sigBy(keys[idx], ap);
        }
        uint256 required = gate.requiredApprovals(amount);
        if (distinct < required) {
            _pay(ap, s, abi.encodeWithSelector(T.InsufficientApprovals.selector, distinct, required));
        } else if (amount > 2000e6) {
            _pay(ap, s, abi.encodeWithSelector(E.OverPerRequestLimit.selector)); // module limits still apply
        } else {
            _pay(ap, s, "");
        }
    }
}
