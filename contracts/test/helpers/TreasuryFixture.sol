// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;
import {SafeTestHelper} from "./SafeTestHelper.sol";
import {ISafeWallet} from "../../src/interfaces/ISafeWallet.sol";
import {ITreasuryPilotModule as I} from "../../src/interfaces/ITreasuryPilotModule.sol";
import {Enum} from "@safe-global/safe-contracts/contracts/common/Enum.sol";
import {TestUSDC} from "../../src/test-assets/TestUSDC.sol";
import {MockAavePool} from "../../src/test-assets/MockAavePool.sol";
import {TreasuryPilotModule} from "../../src/TreasuryPilotModule.sol";
import {TreasuryPilotModuleFactory} from "../../src/TreasuryPilotModuleFactory.sol";

abstract contract TreasuryFixture is SafeTestHelper {
    uint256 internal constant APPROVER_KEY = 7; // deliberately public synthetic fixture identity
    address internal approver;
    address internal executor = address(0xE001);
    address internal guardian = address(0xCA01);
    address internal vendor = address(0xBEEF);
    TestUSDC internal token;
    MockAavePool internal pool;
    ISafeWallet internal treasury;
    ISafeWallet internal op1;
    ISafeWallet internal op2;
    TreasuryPilotModule internal implementation;
    TreasuryPilotModuleFactory internal factory;
    TreasuryPilotModule internal module;
    I.MandateInit internal config;

    function setUp() public virtual {
        vm.warp(10 days);
        approver = vm.addr(APPROVER_KEY);
        token = _createToken();
        pool = new MockAavePool(address(token));
        treasury = deployOneOfOneSafe(address(this), 1);
        op1 = deployOneOfOneSafe(address(this), 2);
        op2 = deployOneOfOneSafe(address(this), 3);
        implementation = new TreasuryPilotModule();
        factory = new TreasuryPilotModuleFactory(address(implementation));
        config = I.MandateInit(
            uint64(block.timestamp),
            uint64(block.timestamp + 365 days),
            300,
            executor,
            guardian,
            I.Limits(2000e6, 10000e6),
            I.Limits(2500e6, 12000e6),
            14 days,
            I.Limits(5000e6, 20000e6)
        );
        address[] memory operational = new address[](2);
        operational[0] = address(op1);
        operational[1] = address(op2);
        address[] memory approvers = new address[](1);
        approvers[0] = approver;
        I.BufferInit[] memory buffers = new I.BufferInit[](3);
        buffers[0] = I.BufferInit(address(treasury), 1000e6, 0);
        buffers[1] = I.BufferInit(address(op1), 10e6, 150e6);
        buffers[2] = I.BufferInit(address(op2), 10e6, 150e6);
        // Factory constructor performs no CREATE, so its first clone uses nonce 1.
        module = TreasuryPilotModule(
            address(uint160(uint256(keccak256(abi.encodePacked(hex"d694", address(factory), hex"01")))))
        );
        _safeTx(
            treasury,
            address(factory),
            abi.encodeCall(factory.create, (address(token), operational, config, approvers, buffers, address(pool)))
        );
        _safeTx(treasury, address(treasury), abi.encodeCall(ISafeWallet.enableModule, (address(module))));
        _safeTx(op1, address(op1), abi.encodeCall(ISafeWallet.enableModule, (address(module))));
        _safeTx(op2, address(op2), abi.encodeCall(ISafeWallet.enableModule, (address(module))));
        token.mint(address(treasury), 30000e6);
        token.mint(address(op1), 10000e6);
        token.mint(address(op2), 10000e6);
        token.mint(address(pool), 30000e6);
        _owner(abi.encodeCall(module.addPayee, (vendor)));
        vm.warp(block.timestamp + 300);
    }

    function _safeTx(ISafeWallet safe, address target, bytes memory data) internal {
        require(
            safe.execTransaction(
                target,
                0,
                data,
                Enum.Operation.Call,
                0,
                0,
                0,
                address(0),
                payable(address(0)),
                approvedHashSignature(address(this))
            ),
            "owner tx failed"
        );
    }

    function _createToken() internal virtual returns (TestUSDC) {
        return new TestUSDC();
    }

    function _owner(bytes memory data) internal {
        _safeTx(treasury, address(module), data);
    }

    function _approval(uint256 id, uint256 amount) internal view returns (I.PaymentApproval memory ap) {
        ap = I.PaymentApproval(
            bytes32(id),
            keccak256("synthetic invoice"),
            keccak256(abi.encode("fingerprint", id)),
            address(module),
            address(op1),
            address(token),
            vendor,
            amount,
            0,
            0,
            uint64(block.timestamp + 1 days),
            keccak256("synthetic terms"),
            uint64(block.timestamp + 14 days)
        );
    }

    function _sign(I.PaymentApproval memory ap) internal view returns (bytes memory) {
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(APPROVER_KEY, module.hashApproval(ap));
        return abi.encode(approver, abi.encodePacked(r, s, v));
    }

    function _pay(I.PaymentApproval memory ap, bytes32 step) internal {
        bytes memory signature = _sign(ap);
        vm.prank(executor);
        module.pay(ap, signature, step);
    }

    function _refill(I.PaymentApproval memory ap, bytes32 step, uint256 amount) internal {
        bytes memory signature = _sign(ap);
        vm.prank(executor);
        module.refill(ap, signature, step, ap.payingWallet, amount);
    }

    function _expectPayError(I.PaymentApproval memory ap, bytes4 selector) internal {
        bytes memory signature = _sign(ap);
        vm.expectRevert(selector);
        vm.prank(executor);
        module.pay(ap, signature, keccak256("rejected step"));
    }
}
