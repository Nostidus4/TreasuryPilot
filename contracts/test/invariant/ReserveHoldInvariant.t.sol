// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;
import {TreasuryFixture} from "../helpers/TreasuryFixture.sol";
import {Vm} from "../helpers/Vm.sol";
import {ReserveHoldExecutor} from "../../src/ReserveHoldExecutor.sol";
import {TreasuryPilotModule} from "../../src/TreasuryPilotModule.sol";
import {ITreasuryPilotModule as I} from "../../src/interfaces/ITreasuryPilotModule.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";

/// @notice Drives reservations, holds, releases and spends through the gate with ghost accounting of R and L.
contract ReserveHandler {
    Vm internal constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));
    uint256 internal constant IDS = 32;
    ReserveHoldExecutor public immutable gate;
    TreasuryPilotModule public immutable module;
    IERC20 public immutable token;
    address public immutable executor;
    address public immutable owner;
    address public immutable vendor;
    address[3] public wallets;
    uint256 public violations;
    uint256 public reserves;
    uint256 public holds;
    uint256 public pays;
    uint256 public blockedSpends;
    mapping(bytes32 => uint256) public expectedReserved;
    mapping(bytes32 => uint256) public expectedHeld;
    uint256 internal nonce;

    constructor(ReserveHoldExecutor gate_, address vendor_, address op1_, address op2_) {
        gate = gate_;
        module = TreasuryPilotModule(address(gate_.module()));
        token = IERC20(module.asset());
        executor = gate_.operator();
        owner = module.safeT();
        vendor = vendor_;
        wallets = [owner, op1_, op2_];
    }

    function _flag(uint256 id, bool failed) internal {
        if (failed) violations |= uint256(1) << id;
    }

    function _id(uint256 seed) internal pure returns (bytes32) {
        return bytes32(seed % IDS + 1);
    }

    function _committed() internal view returns (uint256 total) {
        for (uint256 i; i < 3; ++i) {
            total += gate.committedOf(address(token), wallets[i]);
        }
    }

    function reserve(uint256 seed) external {
        bytes32 id = _id(seed);
        address wallet = wallets[(seed >> 8) % 3];
        uint256 amount = (seed >> 16) % 9000e6 + 1;
        uint256 before = _committed();
        vm.prank(executor);
        try gate.reserve(id, address(token), wallet, amount) {
            ++reserves;
            expectedReserved[id] = amount;
            _flag(2, _committed() != before + amount);
        } catch {}
    }

    function beginExecution(uint256 seed) external {
        bytes32 id = _id(seed);
        uint256 before = _committed();
        vm.prank(executor);
        try gate.beginExecution(id) {
            ++holds;
            expectedHeld[id] += expectedReserved[id];
            expectedReserved[id] = 0;
            _flag(3, _committed() != before); // R to L never double counts
        } catch {}
    }

    function release(uint256 seed) external {
        bytes32 id = _id(seed);
        bool byOwner = seed % 2 == 0;
        bool known = module.requestPaid(id) || module.requestCancelled(id);
        bool wasHeld = expectedHeld[id] > 0;
        vm.prank(byOwner ? owner : executor);
        try gate.release(id) {
            _flag(4, !byOwner && wasHeld && !known); // a hold needs a known outcome or the owner
            expectedReserved[id] = 0;
            expectedHeld[id] = 0;
        } catch {}
    }

    function pay(uint256 seed) external {
        bytes32 id = _id(seed);
        uint256 amount = (seed >> 8) % 1500e6 + 1;
        address wallet = wallets[1 + (seed >> 4) % 2];
        I.PaymentApproval memory ap = I.PaymentApproval(
            id,
            keccak256("invoice"),
            keccak256(abi.encode("fingerprint", id)),
            address(module),
            wallet,
            address(token),
            vendor,
            amount,
            0,
            0,
            uint64(block.timestamp + 1 days),
            keccak256("terms"),
            uint64(block.timestamp + 14 days),
            false
        );
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(7, module.hashApproval(ap));
        bytes memory sig = abi.encode(vm.addr(7), abi.encodePacked(r, s, v));
        bytes32 step = keccak256(abi.encode("step", ++nonce));
        vm.prank(executor);
        try gate.pay(ap, sig, step, amount) {
            ++pays;
            expectedReserved[id] = 0;
            expectedHeld[id] = 0;
        } catch {
            ++blockedSpends;
        }
    }

    function supply(uint256 seed) external {
        bytes32 step = keccak256(abi.encode("step", ++nonce));
        vm.prank(executor);
        try gate.supply(step, seed % 5000e6 + 1) {} catch {}
    }

    function refill(uint256 seed) external {
        bytes32 id = _id(seed);
        address wallet = wallets[1 + (seed >> 4) % 2];
        uint256 amount = (seed >> 8) % 2500e6 + 1;
        I.PaymentApproval memory ap = I.PaymentApproval(
            id,
            keccak256("invoice"),
            keccak256(abi.encode("fingerprint", id)),
            address(module),
            wallet,
            address(token),
            vendor,
            amount,
            0,
            0,
            uint64(block.timestamp + 1 days),
            keccak256("terms"),
            uint64(block.timestamp + 14 days),
            false
        );
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(7, module.hashApproval(ap));
        bytes memory sig = abi.encode(vm.addr(7), abi.encodePacked(r, s, v));
        bytes32 step = keccak256(abi.encode("step", ++nonce));
        vm.prank(executor);
        try gate.refill(ap, sig, step, wallet, amount) {} catch {}
    }

    function advanceTime(uint256 seed) external {
        vm.warp(block.timestamp + seed % 2 days);
    }
}

contract ReserveHoldInvariantTest is TreasuryFixture {
    ReserveHoldExecutor public gate;
    ReserveHandler public handler;

    function setUp() public override {
        super.setUp();
        gate = new ReserveHoldExecutor(module, executor);
        I.MandateInit memory m = config;
        m.executor = address(gate);
        m.validFrom = uint64(block.timestamp - 300);
        _owner(abi.encodeCall(module.configureMandate, (m)));
        handler = new ReserveHandler(gate, vendor, address(op1), address(op2));
        handler.reserve(0 | (uint256(1) << 8) | (uint256(100e6) << 16)); // id 1 on op1
        require(handler.reserves() == 1, "fixture must reserve");
        handler.beginExecution(0);
        require(handler.holds() == 1, "fixture must hold");
    }

    function targetContracts() external view returns (address[] memory targets) {
        targets = new address[](1);
        targets[0] = address(handler);
    }

    /// @notice Acceptance criterion: reservations plus holds never exceed balance minus buffer.
    function invariant_R1_CommitmentsNeverExceedBalanceMinusBuffer() external view {
        for (uint256 i; i < 3; ++i) {
            address w = handler.wallets(i);
            uint256 bal = token.balanceOf(w);
            uint256 buf = module.bufferOf(address(token), w);
            require(bal >= buf && gate.committedOf(address(token), w) <= bal - buf, "over-committed");
        }
    }

    function invariant_R2_TotalsEqualPerRequestLedger() external view {
        uint256 sumR;
        uint256 sumH;
        for (uint256 id = 1; id <= 32; ++id) {
            (,, uint128 r, uint128 h) = gate.commitments(bytes32(id));
            require(r == handler.expectedReserved(bytes32(id)), "ghost R");
            require(h == handler.expectedHeld(bytes32(id)), "ghost L");
            sumR += r;
            sumH += h;
        }
        uint256 totR;
        uint256 totH;
        for (uint256 i; i < 3; ++i) {
            totR += gate.reservedOf(address(token), handler.wallets(i));
            totH += gate.heldOf(address(token), handler.wallets(i));
        }
        require(sumR == totR && sumH == totH, "totals");
    }

    function invariant_R3_NoFlaggedTransitions() external view {
        require(handler.violations() == 0, "R->L double count, or hold released without a known outcome");
    }
}
