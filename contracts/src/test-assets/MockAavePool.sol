// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;
import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {IAavePool} from "../interfaces/IAavePool.sol";

/// @notice TEST ONLY. Synthetic accounting, not an Aave risk/interest model.
contract MockAToken is ERC20 {
    address public immutable UNDERLYING_ASSET_ADDRESS;
    address public immutable POOL;

    constructor(address underlying) ERC20("TEST Aave USD Coin", "aTESTUSDC") {
        UNDERLYING_ASSET_ADDRESS = underlying;
        POOL = msg.sender;
    }

    function decimals() public pure override returns (uint8) {
        return 6;
    }

    function mint(address to, uint256 amount) external {
        require(msg.sender == POOL, "pool only");
        _mint(to, amount);
    }

    function burn(address from, uint256 amount) external {
        require(msg.sender == POOL, "pool only");
        _burn(from, amount);
    }
}

contract MockAavePool is IAavePool {
    address public immutable asset;
    MockAToken public immutable aToken;
    uint256 public healthFactor = type(uint256).max;
    uint256 public healthFactorAfterBorrow = 2e18;
    uint128 public variableBorrowRate = 3e25;
    mapping(address => uint256) public debt;

    constructor(address asset_) {
        asset = asset_;
        aToken = new MockAToken(asset_);
    }

    function setHealthFactor(uint256 value) external {
        healthFactor = value;
    }

    function setHealthFactorAfterBorrow(uint256 value) external {
        healthFactorAfterBorrow = value;
    }

    function setRate(uint128 value) external {
        variableBorrowRate = value;
    }

    function getReserveData(address asset_) external view returns (ReserveData memory data) {
        require(asset_ == asset, "unknown asset");
        data.aTokenAddress = address(aToken);
        data.liquidityIndex = 1e27;
        data.variableBorrowIndex = 1e27;
        data.currentVariableBorrowRate = variableBorrowRate;
    }

    function supply(address asset_, uint256 amount, address onBehalfOf, uint16) external {
        require(asset_ == asset, "unknown asset");
        require(IERC20(asset).transferFrom(msg.sender, address(this), amount), "transfer failed");
        aToken.mint(onBehalfOf, amount);
    }

    function withdraw(address asset_, uint256 amount, address to) external returns (uint256) {
        require(asset_ == asset, "unknown asset");
        aToken.burn(msg.sender, amount);
        require(IERC20(asset).transfer(to, amount), "transfer failed");
        return amount;
    }

    function borrow(address asset_, uint256 amount, uint256 rateMode, uint16, address onBehalfOf) external {
        require(asset_ == asset && rateMode == 2 && msg.sender == onBehalfOf, "wrong borrow");
        debt[onBehalfOf] += amount;
        healthFactor = healthFactorAfterBorrow;
        require(IERC20(asset).transfer(msg.sender, amount), "transfer failed");
    }

    function repay(address asset_, uint256 amount, uint256 rateMode, address onBehalfOf)
        external
        returns (uint256 paid)
    {
        require(asset_ == asset && rateMode == 2, "wrong repay");
        paid = amount > debt[onBehalfOf] ? debt[onBehalfOf] : amount;
        require(IERC20(asset).transferFrom(msg.sender, address(this), paid), "transfer failed");
        debt[onBehalfOf] -= paid;
        if (debt[onBehalfOf] == 0) healthFactor = type(uint256).max;
    }

    function getUserAccountData(address user)
        external
        view
        returns (uint256, uint256, uint256, uint256, uint256, uint256)
    {
        return (aToken.balanceOf(user), debt[user], 0, 8000, 7500, healthFactor);
    }
}
