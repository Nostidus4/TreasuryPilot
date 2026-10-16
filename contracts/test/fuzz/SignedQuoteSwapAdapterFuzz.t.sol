// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;
import {SwapAdapterFixture} from "../helpers/SwapAdapterFixture.sol";
import {ISignedQuoteSwapAdapter as A} from "../../src/interfaces/ISignedQuoteSwapAdapter.sol";
import {SwapQuoteHash} from "../../src/libraries/SwapQuoteHash.sol";

contract SignedQuoteSwapAdapterFuzzTest is SwapAdapterFixture {
    function _tryDirect(uint256 amountIn, uint256 minOut) internal returns (bool ok, bytes4 reason) {
        _safeTx(treasury, address(token), abi.encodeCall(token.approve, (address(adapter), amountIn)));
        vm.prank(address(treasury));
        try adapter.swap(amountIn, minOut, address(treasury)) {
            ok = true;
        } catch (bytes memory err) {
            reason = bytes4(err);
        }
    }

    /// The swap succeeds exactly when the venue's delivered output meets both the signed floor and the caller's
    /// minOut; on success Safe T receives exactly that output, on failure nothing moves.
    function testFuzzSwapSucceedsIffOutputMeetsFloors(
        uint256 amountIn,
        uint256 num,
        uint256 den,
        uint256 signedFloor,
        uint256 callerMinOut
    ) external {
        amountIn = bound(amountIn, 1, 100e6);
        num = bound(num, 1, 1000);
        den = bound(den, 1, 1000);
        signedFloor = bound(signedFloor, 1, 200_000e6);
        callerMinOut = bound(callerMinOut, signedFloor, 200_000e6);
        venue.setRate(num, den);
        uint256 delivered = amountIn * num / den;
        _stage(amountIn, signedFloor);
        uint256 cashBefore = token.balanceOf(address(treasury));
        (bool ok, bytes4 reason) = _tryDirect(amountIn, callerMinOut);
        if (delivered >= callerMinOut && delivered > 0) {
            require(ok, "must succeed");
            require(output.balanceOf(address(treasury)) == delivered, "output exact");
            require(token.balanceOf(address(treasury)) == cashBefore - amountIn, "input exact");
        } else {
            require(!ok && reason == A.InsufficientOutput.selector, "must revert on floor");
            require(
                output.balanceOf(address(treasury)) == 0 && token.balanceOf(address(treasury)) == cashBefore, "no move"
            );
        }
        require(token.balanceOf(address(adapter)) == 0 && output.balanceOf(address(adapter)) == 0, "adapter empty");
        require(token.allowance(address(adapter), address(venue)) == 0, "venue allowance");
    }

    /// A caller minOut below the signed floor is always rejected, whatever the venue pays.
    function testFuzzCallerMinOutBelowSignedFloorAlwaysRejected(uint256 floor, uint256 minOut) external {
        floor = bound(floor, 2, 1_000e6);
        minOut = bound(minOut, 0, floor - 1);
        _stage(10e6, floor);
        (bool ok, bytes4 reason) = _tryDirect(10e6, minOut);
        require(!ok && reason == A.QuoteMismatch.selector, "floor must bind");
    }

    /// Only an allowlisted signer ever stages a quote, for any key and nonce.
    function testFuzzUnknownSignerNeverStages(uint256 key, uint256 nonce) external {
        key = bound(key, 1, 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364140);
        vm.assume(vm.addr(key) != signer);
        bytes memory route = _route(10e6);
        SwapQuoteHash.SwapQuote memory q = _quote(10e6, 19e6, route);
        q.nonce = nonce;
        bytes memory sig = _signQuote(key, q);
        vm.expectRevert(A.SignerNotAllowed.selector);
        adapter.submitQuote(q, route, sig);
    }

    /// A staged quote is usable through its expiry second and never after, and never beyond the TTL cap.
    function testFuzzExpiryWindow(uint64 ttl, uint64 wait) external {
        ttl = uint64(bound(ttl, 0, 2 * TTL));
        wait = uint64(bound(wait, 0, 3 * TTL));
        bytes memory route = _route(10e6);
        SwapQuoteHash.SwapQuote memory q = _quote(10e6, 19e6, route);
        q.expiry = uint64(block.timestamp) + ttl;
        bytes memory sig = _signQuote(SIGNER_KEY, q);
        if (ttl > TTL) {
            vm.expectRevert(A.QuoteTtlTooLong.selector);
            adapter.submitQuote(q, route, sig);
            return;
        }
        adapter.submitQuote(q, route, sig);
        vm.warp(block.timestamp + wait);
        (bool ok, bytes4 reason) = _tryDirect(10e6, 19e6);
        if (wait <= ttl) require(ok, "valid until expiry");
        else require(!ok && reason == A.QuoteExpired.selector, "expired");
    }

    /// A nonce is consumable once per signer, regardless of the quote contents.
    function testFuzzNonceConsumedOnce(uint256 nonce, uint256 amountA, uint256 amountB) external {
        amountA = bound(amountA, 1, 100e6);
        amountB = bound(amountB, 1, 100e6);
        bytes memory routeA = _route(amountA);
        SwapQuoteHash.SwapQuote memory a = _quote(amountA, 1, routeA);
        a.nonce = nonce;
        adapter.submitQuote(a, routeA, _signQuote(SIGNER_KEY, a));
        bytes memory routeB = _route(amountB);
        SwapQuoteHash.SwapQuote memory b = _quote(amountB, 1, routeB);
        b.nonce = nonce;
        bytes memory sigB = _signQuote(SIGNER_KEY, b);
        vm.expectRevert(A.NonceUsed.selector);
        adapter.submitQuote(b, routeB, sigB);
    }

    /// Flipping any bit of a valid signature never yields a staged quote.
    function testFuzzCorruptedSignatureNeverStages(uint8 byteIndex, uint8 bit) external {
        bytes memory route = _route(10e6);
        SwapQuoteHash.SwapQuote memory q = _quote(10e6, 19e6, route);
        bytes memory sig = _signQuote(SIGNER_KEY, q);
        sig[byteIndex % 65] = bytes1(uint8(sig[byteIndex % 65]) ^ uint8(1 << (bit % 8)));
        try adapter.submitQuote(q, route, sig) {
            revert("corrupted signature staged");
        } catch (bytes memory err) {
            bytes4 s = bytes4(err);
            require(s == A.BadSignature.selector || s == A.SignerNotAllowed.selector, "reason");
        }
    }

    function bound(uint256 x, uint256 lo, uint256 hi) internal pure returns (uint256) {
        if (x >= lo && x <= hi) return x;
        return lo + (x % (hi - lo + 1));
    }
}
