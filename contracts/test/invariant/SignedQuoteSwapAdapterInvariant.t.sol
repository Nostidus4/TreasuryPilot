// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;
import {SwapAdapterFixture} from "../helpers/SwapAdapterFixture.sol";
import {SignedQuoteSwapAdapter} from "../../src/SignedQuoteSwapAdapter.sol";
import {SwapQuoteHash} from "../../src/libraries/SwapQuoteHash.sol";
import {MockSwapVenue} from "../../src/test-assets/MockSwapVenue.sol";
import {TestUSDC} from "../../src/test-assets/TestUSDC.sol";
import {Vm} from "../helpers/Vm.sol";

/// @notice Random sequences of staging, swapping, warping, pausing, signer changes and venue price moves with
/// ghost accounting of every successful swap.
contract SwapAdapterHandler {
    Vm internal constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));
    SignedQuoteSwapAdapter public immutable adapter;
    MockSwapVenue public immutable venue;
    TestUSDC public immutable input;
    TestUSDC public immutable output;
    address public immutable safe;
    uint256 public immutable signerKey;
    address public immutable signer;
    address public immutable guardian;

    uint256 public nextNonce = 1;
    uint256 public stages;
    uint256 public swaps;
    uint256 public violations;
    uint256 public totalIn;
    uint256 public totalOut;
    uint256 public totalFloor;
    mapping(uint256 => bool) public stagedNonce;
    mapping(uint256 => uint256) public stageCount;
    uint256 public maxStageCount;

    constructor(SignedQuoteSwapAdapter adapter_, MockSwapVenue venue_, uint256 signerKey_, address guardian_) {
        adapter = adapter_;
        venue = venue_;
        input = TestUSDC(address(venue_.tokenIn()));
        output = TestUSDC(address(venue_.tokenOut()));
        safe = adapter_.governance();
        signerKey = signerKey_;
        signer = vm.addr(signerKey_);
        guardian = guardian_;
    }

    function _flag(uint256 id, bool failed) internal {
        if (failed) violations |= uint256(1) << id;
    }

    function stage(uint256 seed) external {
        uint256 amountIn = seed % 100e6 + 1;
        uint256 floor = (seed >> 64) % (amountIn * 3) + 1;
        // Half the time reuse a past nonce to try a replay.
        uint256 nonce = seed % 2 == 0 ? nextNonce++ : (nextNonce > 1 ? (seed >> 128) % (nextNonce - 1) + 1 : 1);
        uint64 ttl = uint64((seed >> 192) % 11 minutes);
        bytes memory route = abi.encodeCall(venue.swapExact, (amountIn, address(adapter)));
        SwapQuoteHash.SwapQuote memory q = SwapQuoteHash.SwapQuote(
            safe,
            safe,
            address(input),
            address(output),
            amountIn,
            floor,
            address(venue),
            keccak256(route),
            uint64(block.timestamp) + ttl,
            nonce
        );
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(signerKey, adapter.quoteDigest(q));
        bool alreadyUsed = adapter.nonceUsed(signer, nonce);
        try adapter.submitQuote(q, route, abi.encodePacked(r, s, v)) {
            ++stages;
            ++stageCount[nonce];
            if (stageCount[nonce] > maxStageCount) maxStageCount = stageCount[nonce];
            _flag(1, alreadyUsed); // a used nonce must never stage again
        } catch {}
    }

    function swap(uint256 seed) external {
        uint256 amountIn = seed % 100e6 + 1;
        uint256 minOut = (seed >> 64) % (amountIn * 3) + 1;
        uint256 outBefore = output.balanceOf(safe);
        uint256 inBefore = input.balanceOf(safe);
        vm.prank(safe);
        input.approve(address(adapter), amountIn);
        vm.prank(safe);
        try adapter.swap(amountIn, minOut, safe) returns (uint256 out) {
            ++swaps;
            totalIn += amountIn;
            totalOut += out;
            totalFloor += minOut;
            _flag(2, out < minOut);
            _flag(3, output.balanceOf(safe) - outBefore != out);
            _flag(4, inBefore - input.balanceOf(safe) != amountIn);
        } catch {
            _flag(5, output.balanceOf(safe) != outBefore || input.balanceOf(safe) != inBefore);
        }
        vm.prank(safe);
        input.approve(address(adapter), 0);
    }

    function warp(uint256 seed) external {
        vm.warp(block.timestamp + seed % 6 minutes);
    }

    function movePrice(uint256 seed) external {
        venue.setRate(seed % 4 + 1, 1);
    }

    function togglePause(uint256 seed) external {
        if (seed % 2 == 0) {
            vm.prank(guardian);
            adapter.pause();
        } else if (adapter.paused()) {
            vm.prank(safe);
            adapter.resume();
        }
    }

    function toggleSigner(uint256 seed) external {
        vm.prank(safe);
        adapter.setSigner(signer, seed % 2 == 0);
    }
}

contract SignedQuoteSwapAdapterInvariantTest is SwapAdapterFixture {
    SwapAdapterHandler public handler;

    function setUp() public override {
        super.setUp();
        handler = new SwapAdapterHandler(adapter, venue, SIGNER_KEY, guardian);
        // Handler calls the adapter directly as Safe T through vm.prank; the module path is covered by unit tests.
        handler.stage(2); // fixtures must exercise the happy path
        handler.swap(2);
    }

    function targetContracts() external view returns (address[] memory targets) {
        targets = new address[](1);
        targets[0] = address(handler);
    }

    /// The adapter never custodies funds across transactions.
    function invariant_A1_AdapterHoldsNothingAndNoAllowanceRemains() external view {
        require(token.balanceOf(address(adapter)) == 0 && output.balanceOf(address(adapter)) == 0, "custody");
        require(token.allowance(address(adapter), address(venue)) == 0, "venue allowance");
        require(token.allowance(address(treasury), address(adapter)) == 0, "safe allowance");
    }

    /// Replay protection: a (signer, nonce) pair stages at most once.
    function invariant_A2_NoNonceStagedTwice() external view {
        require(handler.maxStageCount() <= 1, "nonce replay");
    }

    /// Every successful swap delivered at least the floor it was called with, in exact deltas.
    function invariant_A3_NoFlaggedSwapViolations() external view {
        require(handler.violations() == 0, "swap accounting violated");
    }

    /// Conservation: Safe T's balances move by exactly the ghost totals.
    function invariant_A4_SafeBalancesMatchGhostTotals() external view {
        require(output.balanceOf(address(treasury)) == handler.totalOut(), "output total");
        require(token.balanceOf(address(treasury)) == 30000e6 - handler.totalIn(), "input total");
        require(handler.totalOut() >= handler.totalFloor(), "slippage floor");
    }

    /// Each swap consumes a staged quote, so swaps never outnumber stages.
    function invariant_A5_SwapsNeverExceedStages() external view {
        require(handler.swaps() <= handler.stages(), "swap without quote");
    }

    function testHandlerFixtureExercisesBothPaths() external view {
        require(handler.stages() == 1 && handler.swaps() == 1, "fixture path");
    }
}
