// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

/// @notice TEST ONLY: swaps between two fixed ERC20s at a fixed base-unit rate.
/// Never unwraps output or transfers native tokens; executor gas is funded manually.
contract TestRouter {
    using SafeERC20 for IERC20;
    address public immutable tokenIn;
    address public immutable tokenOut;
    uint256 public immutable numerator;
    uint256 public immutable denominator;

    constructor(address tokenIn_, address tokenOut_, uint256 numerator_, uint256 denominator_) {
        require(tokenIn_ != tokenOut_ && numerator_ > 0 && denominator_ > 0, "invalid test pair");
        tokenIn = tokenIn_;
        tokenOut = tokenOut_;
        numerator = numerator_;
        denominator = denominator_;
    }

    /// @notice Pays ERC20 output from the router's funded inventory.
    function swap(uint256 amountIn, uint256 minOut, address recipient) external returns (uint256 amountOut) {
        amountOut = amountIn * numerator / denominator;
        require(amountOut >= minOut, "minOut");
        IERC20(tokenIn).safeTransferFrom(msg.sender, address(this), amountIn);
        IERC20(tokenOut).safeTransfer(recipient, amountOut);
    }
}
