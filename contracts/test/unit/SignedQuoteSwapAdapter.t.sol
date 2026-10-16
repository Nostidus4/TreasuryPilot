// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;
import {SwapAdapterFixture} from "../helpers/SwapAdapterFixture.sol";
import {SignedQuoteSwapAdapter} from "../../src/SignedQuoteSwapAdapter.sol";
import {ISignedQuoteSwapAdapter as A} from "../../src/interfaces/ISignedQuoteSwapAdapter.sol";
import {SwapQuoteHash} from "../../src/libraries/SwapQuoteHash.sol";
import {TreasuryPilotErrors as E} from "../../src/libraries/TreasuryPilotErrors.sol";
import {ITreasuryPilotModule as I} from "../../src/interfaces/ITreasuryPilotModule.sol";
import {MockSwapVenue} from "../../src/test-assets/MockSwapVenue.sol";
import {TestUSDC} from "../../src/test-assets/TestUSDC.sol";

contract SignedQuoteSwapAdapterTest is SwapAdapterFixture {
    address internal stranger = address(0xBAD1);

    // ---------------------------------------------------------------- happy path and EIP-712

    function testSignedQuoteSwapThroughModuleEndToEnd() external {
        uint256 cashBefore = token.balanceOf(address(treasury));
        SwapQuoteHash.SwapQuote memory q = _stage(100e6, 190e6);
        _swapViaModule(bytes32(uint256(1)), 100e6, 190e6);
        require(output.balanceOf(address(treasury)) == 200e6, "output to Safe T");
        require(token.balanceOf(address(treasury)) == cashBefore - 100e6, "exact input");
        require(token.allowance(address(treasury), address(adapter)) == 0, "safe allowance cleared");
        require(token.allowance(address(adapter), address(venue)) == 0, "venue allowance cleared");
        require(token.balanceOf(address(adapter)) == 0 && output.balanceOf(address(adapter)) == 0, "adapter empty");
        require(module.stepUsed(bytes32(uint256(1))), "step consumed");
        require(adapter.nonceUsed(signer, q.nonce), "nonce consumed");
        require(adapter.stagedQuote(q.taker, q.recipient, q.amountIn).signer == address(0), "staged cleared");
    }

    function testDigestMatchesIndependentEip712Construction() external {
        bytes memory route = _route(5e6);
        SwapQuoteHash.SwapQuote memory q = _quote(5e6, 9e6, route);
        bytes32 domain = keccak256(
            abi.encode(
                keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"),
                keccak256("TreasuryPilot Swap Quote"),
                keccak256("1"),
                block.chainid,
                address(adapter)
            )
        );
        bytes32 structHash = keccak256(
            abi.encode(
                keccak256(
                    "SwapQuote(address taker,address recipient,address tokenIn,address tokenOut,uint256 amountIn,uint256 minAmountOut,address venue,bytes32 routeHash,uint64 expiry,uint256 nonce)"
                ),
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
            )
        );
        require(adapter.domainSeparator() == domain, "domain");
        require(adapter.quoteDigest(q) == keccak256(abi.encodePacked(hex"1901", domain, structHash)), "digest");
    }

    function testAdapterSurfaceMatchesTestRouterConfiguration() external view {
        require(adapter.tokenIn() == address(token) && adapter.tokenOut() == address(output), "pair");
        require(module.swapRouter() == address(adapter) && module.swapTokenOut() == address(output), "module cfg");
        require(adapter.governance() == address(treasury), "governance is Safe T");
    }

    // ---------------------------------------------------------------- replay

    function testReplayOfConsumedQuoteIsRejected() external {
        bytes memory route = _route(10e6);
        SwapQuoteHash.SwapQuote memory q = _quote(10e6, 19e6, route);
        bytes memory sig = _signQuote(SIGNER_KEY, q);
        adapter.submitQuote(q, route, sig);
        _swapViaModule(bytes32(uint256(1)), 10e6, 19e6);
        // The same signed quote cannot be staged again, so a second swap has nothing to consume.
        vm.expectRevert(A.NonceUsed.selector);
        adapter.submitQuote(q, route, sig);
        _expectDirectRevert(A.NoStagedQuote.selector, 10e6, 19e6);
    }

    function testStagedQuoteIsSingleUse() external {
        _stage(10e6, 19e6);
        _swapViaModule(bytes32(uint256(1)), 10e6, 19e6);
        vm.expectRevert(E.TransferFailed.selector); // adapter reverts NoStagedQuote inside Safe
        _swapViaModule(bytes32(uint256(2)), 10e6, 19e6);
        require(!module.stepUsed(bytes32(uint256(2))), "failed swap consumed step");
    }

    function testSameNonceFromSameSignerAcrossDifferentQuotesIsRejected() external {
        bytes memory route = _route(10e6);
        SwapQuoteHash.SwapQuote memory q = _quote(10e6, 19e6, route);
        adapter.submitQuote(q, route, _signQuote(SIGNER_KEY, q));
        SwapQuoteHash.SwapQuote memory other = _quote(11e6, 21e6, _route(11e6));
        other.nonce = q.nonce;
        bytes memory otherSig = _signQuote(SIGNER_KEY, other);
        bytes memory otherRoute = _route(11e6);
        vm.expectRevert(A.NonceUsed.selector);
        adapter.submitQuote(other, otherRoute, otherSig);
    }

    function testNonceIsScopedPerSigner() external {
        uint256 key2 = 0xB0B;
        _setSigner(vm.addr(key2), true);
        bytes memory route = _route(10e6);
        SwapQuoteHash.SwapQuote memory q = _quote(10e6, 19e6, route);
        adapter.submitQuote(q, route, _signQuote(SIGNER_KEY, q));
        bytes memory route2 = _route(11e6);
        SwapQuoteHash.SwapQuote memory q2 = _quote(11e6, 21e6, route2);
        q2.nonce = q.nonce;
        adapter.submitQuote(q2, route2, _signQuote(key2, q2));
        require(adapter.nonceUsed(vm.addr(key2), q.nonce), "second signer nonce");
    }

    // ---------------------------------------------------------------- expiry

    function testExpiredQuoteCannotBeStaged() external {
        bytes memory route = _route(10e6);
        SwapQuoteHash.SwapQuote memory q = _quote(10e6, 19e6, route);
        bytes memory sig = _signQuote(SIGNER_KEY, q);
        vm.warp(q.expiry + 1);
        vm.expectRevert(A.QuoteExpired.selector);
        adapter.submitQuote(q, route, sig);
    }

    function testQuoteExpiresBetweenStagingAndSwap() external {
        SwapQuoteHash.SwapQuote memory q = _stage(10e6, 19e6);
        vm.warp(q.expiry); // expiry second itself is still valid
        require(_swapDirect(10e6, 19e6) == 20e6, "valid at expiry");
        SwapQuoteHash.SwapQuote memory q2 = _stage(10e6, 19e6);
        vm.warp(q2.expiry + 1);
        _expectDirectRevert(A.QuoteExpired.selector, 10e6, 19e6);
        vm.expectRevert(E.TransferFailed.selector);
        _swapViaModule(bytes32(uint256(7)), 10e6, 19e6);
    }

    function testQuoteTtlAboveGovernanceMaximumIsRejected() external {
        bytes memory route = _route(10e6);
        SwapQuoteHash.SwapQuote memory q = _quote(10e6, 19e6, route);
        q.expiry = uint64(block.timestamp + TTL + 1);
        bytes memory sig = _signQuote(SIGNER_KEY, q);
        vm.expectRevert(A.QuoteTtlTooLong.selector);
        adapter.submitQuote(q, route, sig);
        q.expiry = uint64(block.timestamp + TTL);
        adapter.submitQuote(q, route, _signQuote(SIGNER_KEY, q));
    }

    // ---------------------------------------------------------------- signatures

    function testWrongSignerRejected() external {
        bytes memory route = _route(10e6);
        SwapQuoteHash.SwapQuote memory q = _quote(10e6, 19e6, route);
        bytes memory sig = _signQuote(0xDEAD, q);
        vm.expectRevert(A.SignerNotAllowed.selector);
        adapter.submitQuote(q, route, sig);
    }

    function testTamperedQuoteFieldsRecoverAnUnknownSigner() external {
        bytes memory route = _route(10e6);
        SwapQuoteHash.SwapQuote memory q = _quote(10e6, 19e6, route);
        bytes memory sig = _signQuote(SIGNER_KEY, q);
        SwapQuoteHash.SwapQuote memory t = _copy(q);
        t.minAmountOut = 1;
        vm.expectRevert(A.SignerNotAllowed.selector);
        adapter.submitQuote(t, route, sig);
        t = _copy(q);
        t.nonce += 1;
        vm.expectRevert(A.SignerNotAllowed.selector);
        adapter.submitQuote(t, route, sig);
        t = _copy(q);
        t.expiry += 1;
        vm.expectRevert(A.SignerNotAllowed.selector);
        adapter.submitQuote(t, route, sig);
        t = _copy(q);
        t.amountIn += 1;
        bytes memory tRoute = _route(t.amountIn);
        t.routeHash = keccak256(tRoute);
        vm.expectRevert(A.SignerNotAllowed.selector);
        adapter.submitQuote(t, tRoute, sig);
    }

    function testMalformedAndMalleatedSignaturesRejected() external {
        bytes memory route = _route(10e6);
        SwapQuoteHash.SwapQuote memory q = _quote(10e6, 19e6, route);
        vm.expectRevert(A.BadSignature.selector);
        adapter.submitQuote(q, route, hex"1234");
        vm.expectRevert(A.BadSignature.selector);
        adapter.submitQuote(q, route, new bytes(65));
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(SIGNER_KEY, adapter.quoteDigest(q));
        bytes32 highS = bytes32(0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141 - uint256(s));
        vm.expectRevert(A.BadSignature.selector);
        adapter.submitQuote(q, route, abi.encodePacked(r, highS, v == 27 ? uint8(28) : uint8(27)));
    }

    function testSignatureForAnotherAdapterOrChainIsRejected() external {
        address[] memory signers = new address[](1);
        signers[0] = signer;
        SignedQuoteSwapAdapter other =
            new SignedQuoteSwapAdapter(module, address(output), TTL, signers, new address[](0));
        bytes memory route = _route(10e6);
        SwapQuoteHash.SwapQuote memory q = _quote(10e6, 19e6, route);
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(SIGNER_KEY, other.quoteDigest(q));
        vm.expectRevert(A.SignerNotAllowed.selector);
        adapter.submitQuote(q, route, abi.encodePacked(r, s, v));
        // Signed for this adapter on this chain, then replayed on a forked chain id.
        bytes memory sig = _signQuote(SIGNER_KEY, q);
        vm.chainId(block.chainid + 1);
        vm.expectRevert(A.SignerNotAllowed.selector);
        adapter.submitQuote(q, route, sig);
    }

    function testSignerRemovedAfterStagingInvalidatesQuote() external {
        _stage(10e6, 19e6);
        _setSigner(signer, false);
        _expectDirectRevert(A.SignerNotAllowed.selector, 10e6, 19e6);
    }

    function testSignerRemovedBeforeStagingRejected() external {
        _setSigner(signer, false);
        bytes memory route = _route(10e6);
        SwapQuoteHash.SwapQuote memory q = _quote(10e6, 19e6, route);
        bytes memory sig = _signQuote(SIGNER_KEY, q);
        vm.expectRevert(A.SignerNotAllowed.selector);
        adapter.submitQuote(q, route, sig);
    }

    // ---------------------------------------------------------------- binding: pair, taker, recipient, venue, route

    function testQuoteBindingsRejected() external {
        bytes memory route = _route(10e6);
        SwapQuoteHash.SwapQuote memory q = _quote(10e6, 19e6, route);
        SwapQuoteHash.SwapQuote memory t = _copy(q);
        t.tokenOut = address(token);
        _expectSubmitRevert(t, route, A.WrongPair.selector);
        t = _copy(q);
        t.tokenIn = address(output);
        _expectSubmitRevert(t, route, A.WrongPair.selector);
        t = _copy(q);
        t.taker = stranger;
        _expectSubmitRevert(t, route, A.WrongTaker.selector);
        t = _copy(q);
        t.recipient = stranger;
        _expectSubmitRevert(t, route, A.WrongRecipient.selector);
        t = _copy(q);
        t.amountIn = 0;
        _expectSubmitRevert(t, route, A.InvalidAmount.selector);
        t = _copy(q);
        t.minAmountOut = 0;
        _expectSubmitRevert(t, route, A.InvalidAmount.selector);
        t = _copy(q);
        t.venue = stranger;
        _expectSubmitRevert(t, route, A.VenueNotAllowed.selector);
        _expectSubmitRevert(q, _route(11e6), A.RouteHashMismatch.selector);
    }

    function _expectSubmitRevert(SwapQuoteHash.SwapQuote memory q, bytes memory route, bytes4 selector) internal {
        bytes memory sig = _signQuote(SIGNER_KEY, q);
        vm.expectRevert(selector);
        adapter.submitQuote(q, route, sig);
    }

    function testSwapOnlyForSafeTAndToSafeT() external {
        _stage(10e6, 19e6);
        vm.expectRevert(A.NotTaker.selector);
        vm.prank(stranger);
        adapter.swap(10e6, 19e6, stranger);
        vm.expectRevert(A.NotTaker.selector);
        vm.prank(executor);
        adapter.swap(10e6, 19e6, address(treasury));
        vm.expectRevert(A.WrongRecipient.selector);
        vm.prank(address(treasury));
        adapter.swap(10e6, 19e6, stranger);
    }

    function testVenueRemovedAfterStagingRejected() external {
        _stage(10e6, 19e6);
        _safeTx(treasury, address(adapter), abi.encodeCall(adapter.setVenue, (address(venue), false)));
        _expectDirectRevert(A.VenueNotAllowed.selector, 10e6, 19e6);
    }

    function testStagedQuoteForOtherAmountDoesNotApply() external {
        _stage(10e6, 19e6);
        _expectDirectRevert(A.NoStagedQuote.selector, 11e6, 19e6);
    }

    // ---------------------------------------------------------------- slippage / minOut

    function testVenueDeliveringLessThanSignedFloorReverts() external {
        _stage(10e6, 19e6);
        venue.setRate(18, 10); // 18e6 < 19e6
        _expectDirectRevert(A.InsufficientOutput.selector, 10e6, 19e6);
        require(output.balanceOf(address(treasury)) == 0 && token.balanceOf(address(adapter)) == 0, "rolled back");
    }

    function testExecutorMinOutBelowSignedFloorRejected() external {
        _stage(10e6, 19e6);
        _expectDirectRevert(A.QuoteMismatch.selector, 10e6, 18e6);
        vm.expectRevert(E.TransferFailed.selector);
        _swapViaModule(bytes32(uint256(1)), 10e6, 18e6);
    }

    function testExecutorMinOutAboveSignedFloorIsEnforced() external {
        _stage(10e6, 19e6);
        _expectDirectRevert(A.InsufficientOutput.selector, 10e6, 21e6); // venue pays 20e6
        _stage(10e6, 19e6);
        require(_swapDirect(10e6, 20e6) == 20e6, "exact boundary");
    }

    function testExactSignedFloorBoundary() external {
        _stage(10e6, 20e6);
        require(_swapDirect(10e6, 20e6) == 20e6, "== floor passes");
        _stage(10e6, 20e6);
        venue.setRate(20e6 - 1, 10e6);
        _expectDirectRevert(A.InsufficientOutput.selector, 10e6, 20e6);
    }

    function testVenueThatPaysNothingReverts() external {
        bytes memory route = abi.encodeCall(venue.swapNothing, (10e6));
        SwapQuoteHash.SwapQuote memory q = _quote(10e6, 1, route);
        adapter.submitQuote(q, route, _signQuote(SIGNER_KEY, q));
        _expectDirectRevert(A.InsufficientOutput.selector, 10e6, 1);
    }

    function testStrayOutputBalanceCannotSatisfyMinOut() external {
        output.mint(address(adapter), 1_000e6); // donated before the swap
        _stage(10e6, 19e6);
        venue.setRate(1, 1);
        _expectDirectRevert(A.InsufficientOutput.selector, 10e6, 19e6);
    }

    function testStrayBalancesAreNeitherUsedNorForwarded() external {
        output.mint(address(adapter), 7e6);
        token.mint(address(adapter), 3e6);
        _stage(10e6, 19e6);
        require(_swapDirect(10e6, 19e6) == 20e6, "delta only");
        require(output.balanceOf(address(adapter)) == 7e6 && token.balanceOf(address(adapter)) == 3e6, "stray");
    }

    function testPartialFillThatLeavesInputReverts() external {
        _stage(10e6, 1);
        venue.setFillBps(5000);
        _expectDirectRevert(A.InputNotSpentExactly.selector, 10e6, 1);
    }

    function testRevertingVenueCallReverts() external {
        _stage(10e6, 19e6);
        venue.setRate(1, 0); // division by zero inside the venue
        _expectDirectRevert(A.VenueCallFailed.selector, 10e6, 19e6);
    }

    // ---------------------------------------------------------------- reentrancy

    function testVenueCannotReenterSwapOrSubmit() external {
        _stage(10e6, 19e6);
        bytes memory route = _route(10e6);
        SwapQuoteHash.SwapQuote memory spare = _quote(10e6, 19e6, route);
        bytes memory sig = _signQuote(SIGNER_KEY, spare);
        venue.setReenter(address(adapter), abi.encodeCall(adapter.submitQuote, (spare, route, sig)));
        _expectDirectRevert(A.VenueCallFailed.selector, 10e6, 19e6);
        venue.setReenter(address(adapter), abi.encodeCall(adapter.swap, (10e6, 19e6, address(treasury))));
        _expectDirectRevert(A.VenueCallFailed.selector, 10e6, 19e6);
        require(!adapter.nonceUsed(signer, spare.nonce), "reentrant stage rolled back");
    }

    // ---------------------------------------------------------------- pause / guardian / module status

    function testGuardianAndGovernanceCanPauseOnlyGovernanceResumes() external {
        vm.expectRevert(A.NotGuardianOrGovernance.selector);
        vm.prank(stranger);
        adapter.pause();
        vm.prank(guardian);
        adapter.pause();
        require(adapter.paused(), "guardian paused");
        vm.expectRevert(A.NotGovernance.selector);
        vm.prank(guardian);
        adapter.resume();
        vm.expectRevert(A.NotGovernance.selector);
        vm.prank(executor);
        adapter.resume();
        _safeTx(treasury, address(adapter), abi.encodeCall(adapter.resume, ()));
        require(!adapter.paused(), "resumed");
        vm.expectRevert(A.NotPaused.selector);
        vm.prank(address(treasury));
        adapter.resume();
    }

    function testPausedAdapterBlocksStagingAndSwapping() external {
        SwapQuoteHash.SwapQuote memory q = _stage(10e6, 19e6);
        vm.prank(guardian);
        adapter.pause();
        _expectDirectRevert(A.AdapterIsPaused.selector, 10e6, 19e6);
        vm.expectRevert(E.TransferFailed.selector);
        _swapViaModule(bytes32(uint256(1)), 10e6, 19e6);
        bytes memory route = _route(11e6);
        SwapQuoteHash.SwapQuote memory q2 = _quote(11e6, 19e6, route);
        bytes memory sig = _signQuote(SIGNER_KEY, q2);
        vm.expectRevert(A.AdapterIsPaused.selector);
        adapter.submitQuote(q2, route, sig);
        // After resume the earlier staged quote is still valid until its expiry.
        _safeTx(treasury, address(adapter), abi.encodeCall(adapter.resume, ()));
        require(q.expiry >= block.timestamp, "still fresh");
        require(_swapDirect(10e6, 19e6) == 20e6, "resumed swap");
    }

    function testPausedModuleBlocksSwapForGasAndAdapter() external {
        _stage(10e6, 19e6);
        vm.prank(guardian);
        module.pause();
        vm.expectRevert(E.MandatePaused.selector);
        _swapViaModule(bytes32(uint256(1)), 10e6, 19e6);
        // Even called directly by Safe T, the adapter honours the module pause.
        _expectDirectRevert(A.ModuleNotActive.selector, 10e6, 19e6);
        _owner(abi.encodeCall(module.resume, ()));
        _swapViaModule(bytes32(uint256(1)), 10e6, 19e6);
        require(output.balanceOf(address(treasury)) == 20e6, "resumed");
    }

    function testRevokedModuleBlocksAdapter() external {
        _stage(10e6, 19e6);
        _owner(abi.encodeCall(module.revoke, ()));
        _expectDirectRevert(A.ModuleNotActive.selector, 10e6, 19e6);
    }

    // ---------------------------------------------------------------- module limits still apply

    function testModuleLimitsAndBufferStillBoundSignedSwaps() external {
        _stage(101e6, 1);
        vm.expectRevert(E.OverSwapPerTx.selector);
        _swapViaModule(bytes32(uint256(1)), 101e6, 1);
        _stage(100e6, 1);
        _swapViaModule(bytes32(uint256(2)), 100e6, 1);
        _stage(51e6, 1);
        vm.expectRevert(E.OverSwapDaily.selector);
        _swapViaModule(bytes32(uint256(3)), 51e6, 1);
        _stage(50e6, 1);
        _swapViaModule(bytes32(uint256(3)), 50e6, 1);
        require(module.usedToday(module.SWAP_IN(), address(token)) == 150e6, "daily counter");
    }

    function testModuleBufferFloorStillApplies() external {
        _owner(abi.encodeCall(module.setBuffer, (address(treasury), token.balanceOf(address(treasury)), 0)));
        _stage(10e6, 1);
        vm.expectRevert(E.SourceBufferBreach.selector);
        _swapViaModule(bytes32(uint256(1)), 10e6, 1);
    }

    function testOnlyConfiguredExecutorCanTriggerThroughModule() external {
        _stage(10e6, 19e6);
        vm.expectRevert(E.NotExecutor.selector);
        vm.prank(stranger);
        module.swapForGas(bytes32(uint256(1)), 10e6, 19e6);
    }

    // ---------------------------------------------------------------- governance

    function testOnlyGovernanceManagesSignersVenuesAndTtl() external {
        vm.startPrank(stranger);
        vm.expectRevert(A.NotGovernance.selector);
        adapter.setSigner(stranger, true);
        vm.expectRevert(A.NotGovernance.selector);
        adapter.setVenue(address(venue), false);
        vm.expectRevert(A.NotGovernance.selector);
        adapter.setMaxQuoteTtl(1);
        vm.stopPrank();
        vm.startPrank(executor);
        vm.expectRevert(A.NotGovernance.selector);
        adapter.setSigner(executor, true);
        vm.stopPrank();
        vm.startPrank(guardian);
        vm.expectRevert(A.NotGovernance.selector);
        adapter.setSigner(guardian, true);
        vm.stopPrank();
        _safeTx(treasury, address(adapter), abi.encodeCall(adapter.setMaxQuoteTtl, (1 hours)));
        require(adapter.maxQuoteTtl() == 1 hours, "ttl");
    }

    function testGovernanceInputValidation() external {
        vm.startPrank(address(treasury));
        vm.expectRevert(A.InvalidConfiguration.selector);
        adapter.setSigner(address(0), true);
        vm.expectRevert(A.InvalidConfiguration.selector);
        adapter.setMaxQuoteTtl(0);
        vm.expectRevert(A.InvalidConfiguration.selector);
        adapter.setVenue(address(token), true); // a route must not be able to call the input token
        vm.expectRevert(A.InvalidConfiguration.selector);
        adapter.setVenue(address(output), true);
        vm.expectRevert(A.InvalidConfiguration.selector);
        adapter.setVenue(address(adapter), true);
        vm.expectRevert(A.InvalidConfiguration.selector);
        adapter.setVenue(stranger, true); // not a contract
        vm.stopPrank();
    }

    function testConstructorValidation() external {
        address[] memory none = new address[](0);
        vm.expectRevert(A.InvalidConfiguration.selector);
        new SignedQuoteSwapAdapter(module, address(token), TTL, none, none); // tokenOut == asset
        vm.expectRevert(A.InvalidConfiguration.selector);
        new SignedQuoteSwapAdapter(module, address(output), 0, none, none);
        vm.expectRevert(A.InvalidConfiguration.selector);
        new SignedQuoteSwapAdapter(module, stranger, TTL, none, none); // not a contract
        vm.expectRevert(A.InvalidConfiguration.selector);
        new SignedQuoteSwapAdapter(I(stranger), address(output), TTL, none, none);
    }

    function testRouterConfigurationRejectsAdapterForAnotherPair() external {
        TestUSDC third = new TestUSDC();
        vm.expectRevert(E.RouterNotAllowed.selector);
        vm.prank(address(treasury));
        module.configureSwap(address(adapter), address(third), I.Limits(1, 1));
    }

    function _expectDirectRevert(bytes4 selector, uint256 amountIn, uint256 minOut) internal {
        _safeTx(treasury, address(token), abi.encodeCall(token.approve, (address(adapter), amountIn)));
        vm.expectRevert(selector);
        vm.prank(address(treasury));
        adapter.swap(amountIn, minOut, address(treasury));
    }

    function _setSigner(address who, bool allowed) internal {
        _safeTx(treasury, address(adapter), abi.encodeCall(adapter.setSigner, (who, allowed)));
    }
}
