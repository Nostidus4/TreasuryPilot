// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

/// @notice EIP-712 SwapQuote, signed under the "TreasuryPilot Swap Quote" domain (F-065, SC-L03).
/// The domain's verifyingContract is the adapter, so a quote cannot cross adapters, treasuries or chains.
library SwapQuoteHash {
    struct SwapQuote {
        address taker; // the Safe whose funds are swapped; must be the module's Safe T
        address recipient; // receives tokenOut; must equal the swap() recipient
        address tokenIn;
        address tokenOut;
        uint256 amountIn; // exact input, in tokenIn base units
        uint256 minAmountOut; // price floor, in tokenOut base units
        address venue; // DEX or aggregator router the route is sent to
        bytes32 routeHash; // keccak256 of the exact route calldata sent to the venue
        uint64 expiry; // last valid unix second
        uint256 nonce; // unique per signer; consumed when the quote is staged
    }

    bytes32 internal constant TYPEHASH = keccak256(
        "SwapQuote(address taker,address recipient,address tokenIn,address tokenOut,uint256 amountIn,uint256 minAmountOut,address venue,bytes32 routeHash,uint64 expiry,uint256 nonce)"
    );

    function structHash(SwapQuote memory q) internal pure returns (bytes32) {
        return keccak256(
            abi.encode(
                TYPEHASH,
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
    }
}
