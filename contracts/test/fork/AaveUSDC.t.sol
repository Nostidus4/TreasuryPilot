// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;
import {AaveForkFixture} from "./AaveSepolia.t.sol";
import {IAavePool, IAaveToken} from "../../src/interfaces/IAavePool.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {ITreasuryPilotModule as I} from "../../src/interfaces/ITreasuryPilotModule.sol";
import {TreasuryPilotErrors as E} from "../../src/libraries/TreasuryPilotErrors.sol";

interface IATokenRevision {
    function ATOKEN_REVISION() external view returns (uint256);
}

abstract contract USDCForkFixture is AaveForkFixture {
    function _forkAsset() internal pure override returns (address) {
        return 0x94a9D9AC8a22534E3FaCa9F4e7F2E2cf85d5E4C8;
    }

    function _assetUnit() internal pure override returns (uint256) {
        return 1e6;
    }
}

/// @notice Unmodified USDC reserve state with real headroom; only Safe token balances are inserted.
contract AaveUSDCHistoricalForkTest is USDCForkFixture {
    function _forkBlock() internal pure override returns (uint256) {
        return 8000000;
    }

    function test_USDC_SupplyAndWithdrawWithSixDecimals() external {
        require(token.decimals() == 6 && IATokenRevision(_aToken()).ATOKEN_REVISION() == 1, "USDC ABI/revision");
        uint256 cash = token.balanceOf(address(treasury));
        vm.prank(executor);
        module.supply(bytes32(uint256(1)), 100e6);
        uint256 index = IAavePool(POOL).getReserveNormalizedIncome(_forkAsset());
        uint256 shares = IAaveToken(_aToken()).scaledBalanceOf(address(treasury));
        require(shares >= 100e6 * 1e27 / index && shares <= (100e6 * 1e27 + index / 2) / index, "USDC shares");
        require(token.balanceOf(address(treasury)) == cash - 100e6, "USDC exact supply");
        vm.prank(executor);
        module.withdraw(bytes32(uint256(2)), 50e6);
        require(token.balanceOf(address(treasury)) == cash - 50e6, "USDC exact withdrawal");
        require(token.allowance(address(treasury), POOL) == 0, "USDC allowance");
    }

    function test_USDC_D3_WithdrawRefillAndPay() external {
        vm.prank(executor);
        module.supply(bytes32(uint256(1)), 100e6);
        vm.prank(executor);
        module.withdraw(bytes32(uint256(2)), 50e6);
        _safeTx(op1, _forkAsset(), abi.encodeWithSignature("transfer(address,uint256)", address(0xD00D), 9980e6));
        I.PaymentApproval memory ap = _approval(1, 100e6);
        _refill(ap, bytes32(uint256(3)), 90e6);
        _pay(ap, bytes32(uint256(4)));
        require(token.balanceOf(vendor) == 100e6 && token.balanceOf(address(op1)) == 10e6, "USDC settlement");
    }
}

contract AaveUSDCCappedForkTest is USDCForkFixture {
    function test_USDC_FullCapRevertsWithoutConsumingBudget() external {
        uint256 cap = (IAavePool(POOL).getReserveData(_forkAsset()).configuration >> 116) & ((1 << 36) - 1);
        require(cap == 2000000000 && IERC20(_aToken()).totalSupply() > cap * 1e6, "pinned cap state");
        uint256 beforeCash = token.balanceOf(address(treasury));
        vm.expectRevert(E.TransferFailed.selector);
        vm.prank(executor);
        module.supply(bytes32(uint256(1)), 100e6);
        require(
            token.balanceOf(address(treasury)) == beforeCash && module.usedToday(module.SUPPLY(), address(token)) == 0,
            "cap rollback"
        );
        require(!module.stepUsed(bytes32(uint256(1))) && token.allowance(address(treasury), POOL) == 0, "cap effects");
    }
}
