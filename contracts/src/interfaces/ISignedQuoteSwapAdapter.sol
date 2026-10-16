// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;
import {SwapQuoteHash} from "../libraries/SwapQuoteHash.sol";

/// @notice Production swap adapter (F-065, SC-L03). It exposes the same `tokenIn/tokenOut/swap` surface as the
/// test router, so `module.configureSwap(adapter, tokenOut, limits)` and `module.swapForGas` work unchanged.
/// Flow: (1) anyone calls `submitQuote` with a quote signed by an allowlisted signer and its route calldata;
/// (2) the executor calls `module.swapForGas`, which makes Safe T call `swap`, consuming the staged quote.
interface ISignedQuoteSwapAdapter {
    event QuoteStaged(
        bytes32 indexed quoteDigest,
        address indexed signer,
        uint256 amountIn,
        uint256 minAmountOut,
        address venue,
        uint64 expiry,
        uint256 nonce
    );
    event QuoteSwapped(
        bytes32 indexed quoteDigest, address indexed taker, address recipient, uint256 amountIn, uint256 amountOut
    );
    event SignerSet(address indexed signer, bool allowed);
    event VenueSet(address indexed venue, bool allowed);
    event MaxQuoteTtlSet(uint64 maxQuoteTtl);
    event AdapterPaused(address indexed by);
    event AdapterResumed(address indexed by);

    error NotGovernance();
    error NotGuardianOrGovernance();
    error NotTaker();
    error AdapterIsPaused();
    error ModuleNotActive();
    error NotPaused();
    error InvalidConfiguration();
    error SignerNotAllowed();
    error VenueNotAllowed();
    error BadSignature();
    error QuoteExpired();
    error QuoteTtlTooLong();
    error NonceUsed();
    error WrongPair();
    error WrongTaker();
    error WrongRecipient();
    error InvalidAmount();
    error RouteHashMismatch();
    error NoStagedQuote();
    error QuoteMismatch();
    error InsufficientOutput();
    error InputNotSpentExactly();
    error VenueCallFailed();

    /// @notice Signed pair, taker and recipient are checked; the nonce is consumed here (replay protection).
    /// Re-staging a different quote for the same (taker, recipient, amountIn) overwrites the earlier staged one.
    function submitQuote(SwapQuoteHash.SwapQuote calldata quote, bytes calldata route, bytes calldata signature)
        external
        returns (bytes32 digest);

    /// @notice Called by Safe T (via `module.swapForGas`). Consumes the staged quote for
    /// (msg.sender, recipient, amountIn), pulls exactly `amountIn`, executes the signed route on the signed venue,
    /// and requires output >= max(minOut, quote.minAmountOut). Output is paid to `recipient`.
    function swap(uint256 amountIn, uint256 minOut, address recipient) external returns (uint256 amountOut);

    function tokenIn() external view returns (address);
    function tokenOut() external view returns (address);
    function quoteDigest(SwapQuoteHash.SwapQuote calldata quote) external view returns (bytes32);
    function domainSeparator() external view returns (bytes32);

    // Governance (Safe T) and guardian controls.
    function setSigner(address signer, bool allowed) external;
    function setVenue(address venue, bool allowed) external;
    function setMaxQuoteTtl(uint64 maxQuoteTtl_) external;
    function pause() external;
    function resume() external;
}
