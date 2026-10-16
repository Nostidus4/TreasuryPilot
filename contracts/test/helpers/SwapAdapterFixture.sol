// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;
import {TreasuryFixture} from "./TreasuryFixture.sol";
import {ITreasuryPilotModule as I} from "../../src/interfaces/ITreasuryPilotModule.sol";
import {SignedQuoteSwapAdapter} from "../../src/SignedQuoteSwapAdapter.sol";
import {SwapQuoteHash} from "../../src/libraries/SwapQuoteHash.sol";
import {MockSwapVenue} from "../../src/test-assets/MockSwapVenue.sol";
import {TestUSDC} from "../../src/test-assets/TestUSDC.sol";

/// @notice Treasury + signed-quote adapter wired as the module's swap router, with a rate-based mock venue.
abstract contract SwapAdapterFixture is TreasuryFixture {
    uint256 internal constant SIGNER_KEY = 0xA11CE5; // deliberately public synthetic fixture identity
    uint64 internal constant TTL = 10 minutes;
    TestUSDC internal output;
    MockSwapVenue internal venue;
    SignedQuoteSwapAdapter internal adapter;
    address internal signer;
    uint256 internal nextNonce = 1;

    function setUp() public virtual override {
        super.setUp();
        signer = vm.addr(SIGNER_KEY);
        output = new TestUSDC();
        venue = new MockSwapVenue(token, output);
        output.mint(address(venue), 1_000_000e6);
        address[] memory signers = new address[](1);
        signers[0] = signer;
        address[] memory venues = new address[](1);
        venues[0] = address(venue);
        adapter = new SignedQuoteSwapAdapter(module, address(output), TTL, signers, venues);
        _owner(abi.encodeCall(module.configureSwap, (address(adapter), address(output), I.Limits(100e6, 150e6))));
    }

    function _route(uint256 amountIn) internal view returns (bytes memory) {
        return abi.encodeCall(venue.swapExact, (amountIn, address(adapter)));
    }

    function _quote(uint256 amountIn, uint256 minOut, bytes memory route)
        internal
        returns (SwapQuoteHash.SwapQuote memory q)
    {
        q = SwapQuoteHash.SwapQuote(
            address(treasury),
            address(treasury),
            address(token),
            address(output),
            amountIn,
            minOut,
            address(venue),
            keccak256(route),
            uint64(block.timestamp + 5 minutes),
            nextNonce++
        );
    }

    function _signQuote(uint256 key, SwapQuoteHash.SwapQuote memory q) internal view returns (bytes memory) {
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(key, adapter.quoteDigest(q));
        return abi.encodePacked(r, s, v);
    }

    /// Builds, signs and stages a quote for the default route; returns it.
    function _stage(uint256 amountIn, uint256 minOut) internal returns (SwapQuoteHash.SwapQuote memory q) {
        bytes memory route = _route(amountIn);
        q = _quote(amountIn, minOut, route);
        adapter.submitQuote(q, route, _signQuote(SIGNER_KEY, q));
    }

    function _copy(SwapQuoteHash.SwapQuote memory q) internal pure returns (SwapQuoteHash.SwapQuote memory c) {
        c = SwapQuoteHash.SwapQuote(
            q.taker,
            q.recipient,
            q.tokenIn,
            q.tokenOut,
            q.amountIn,
            q.minAmountOut,
            q.venue,
            q.routeHash,
            q.expiry,
            q.nonce
        );
    }

    function _swapViaModule(bytes32 step, uint256 amountIn, uint256 minOut) internal {
        vm.prank(executor);
        module.swapForGas(step, amountIn, minOut);
    }

    /// Calls the adapter as Safe T, bypassing the module, to observe the adapter's own revert reason.
    function _swapDirect(uint256 amountIn, uint256 minOut) internal returns (uint256) {
        _safeTx(treasury, address(token), abi.encodeCall(token.approve, (address(adapter), amountIn)));
        vm.prank(address(treasury));
        return adapter.swap(amountIn, minOut, address(treasury));
    }
}
