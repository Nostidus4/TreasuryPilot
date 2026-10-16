// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

/// @notice TEST ONLY: a DEX-like venue used to exercise the signed-quote adapter. `swapExact` pulls tokenIn from
/// the caller and pays tokenOut at a fixed rate; the knobs model hostile or lossy venues.
contract MockSwapVenue {
    using SafeERC20 for IERC20;

    IERC20 public immutable tokenIn;
    IERC20 public immutable tokenOut;
    uint256 public numerator = 2;
    uint256 public denominator = 1;
    /// @dev Pull only this share of amountIn (bps), modelling a partial fill that leaves input behind.
    uint256 public fillBps = 10_000;
    /// @dev Call this target with `reenterData` during the swap.
    address public reenterTarget;
    bytes public reenterData;

    constructor(IERC20 tokenIn_, IERC20 tokenOut_) {
        tokenIn = tokenIn_;
        tokenOut = tokenOut_;
    }

    function setRate(uint256 n, uint256 d) external {
        numerator = n;
        denominator = d;
    }

    function setFillBps(uint256 bps) external {
        fillBps = bps;
    }

    function setReenter(address target, bytes calldata data) external {
        reenterTarget = target;
        reenterData = data;
    }

    function swapExact(uint256 amountIn, address to) external returns (uint256 amountOut) {
        uint256 pulled = amountIn * fillBps / 10_000;
        tokenIn.safeTransferFrom(msg.sender, address(this), pulled);
        amountOut = pulled * numerator / denominator;
        if (reenterTarget != address(0)) {
            (bool ok,) = reenterTarget.call(reenterData);
            require(ok, "reenter failed");
        }
        tokenOut.safeTransfer(to, amountOut);
    }

    /// @dev Pays no output at all.
    function swapNothing(uint256 amountIn) external {
        tokenIn.safeTransferFrom(msg.sender, address(this), amountIn);
    }
}
