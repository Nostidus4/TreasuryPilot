// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;
import {TreasuryFixture} from "../helpers/TreasuryFixture.sol";
import {TestUSDC} from "../../src/test-assets/TestUSDC.sol";
import {MockAavePool} from "../../src/test-assets/MockAavePool.sol";
import {IAavePool, IAaveToken} from "../../src/interfaces/IAavePool.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {TreasuryPilotErrors as E} from "../../src/libraries/TreasuryPilotErrors.sol";
import {ITreasuryPilotModule as I} from "../../src/interfaces/ITreasuryPilotModule.sol";

/// @notice Actual Aave V3 code/state; only fixture Safe cash is inserted with cheatcodes.
abstract contract AaveForkFixture is TreasuryFixture {
    uint256 internal constant FORK_BLOCK = 11890000;
    address internal constant POOL = 0x6Ae43d3271ff6888e7Fc43Fd7321a503ff738951;
    address internal constant LINK = 0xf8Fb3713D459D7C1018BD0A49D19b4C44290EBE5;

    function setUp() public override {
        vm.createSelectFork(vm.envOr("SEPOLIA_RPC_URL", "https://sepolia.drpc.org"), _forkBlock());
        require(block.chainid == 11155111 && block.number == _forkBlock(), "fork pin");
        require(POOL.code.length != 0 && _forkAsset().code.length != 0, "deployment missing");
        require(_aToken().code.length != 0, "aToken deployment missing");
        super.setUp();
        require(approver.code.length == 0, "fork approver collides with contract");
    }

    function _startTime() internal view override returns (uint256) {
        return block.timestamp;
    }

    function _forkBlock() internal pure virtual returns (uint256) {
        return FORK_BLOCK;
    }

    function _forkAsset() internal pure virtual returns (address) {
        return LINK;
    }

    function _createToken() internal pure override returns (TestUSDC) {
        return TestUSDC(_forkAsset());
    }

    function _createPool() internal pure override returns (MockAavePool) {
        return MockAavePool(POOL);
    }

    function _assetUnit() internal pure virtual override returns (uint256) {
        return 1e18;
    }

    function _approverKey() internal pure override returns (uint256) {
        return 0xdeadbeefcafebabedeadbeefcafebabedeadbeefcafebabedeadbeefcafebabe;
    }

    function _aToken() internal view returns (address) {
        return IAavePool(POOL).getReserveData(_forkAsset()).aTokenAddress;
    }

    function _fundWallet(address wallet, uint256 amount) internal override {
        if (wallet == POOL) return; // Never alter real pool liquidity/accounting.
        for (uint256 slot; slot < 100; ++slot) {
            bytes32 key = keccak256(abi.encode(wallet, slot));
            bytes32 original = vm.load(_forkAsset(), key);
            vm.store(_forkAsset(), key, bytes32(amount));
            if (token.balanceOf(wallet) == amount) return;
            vm.store(_forkAsset(), key, original);
        }
        revert("asset balance slot not found");
    }
}

contract AaveSepoliaForkTest is AaveForkFixture {
    function test_D2_SupplyAccountDataAndAccrual() external {
        uint256 beforeCash = token.balanceOf(address(treasury));
        vm.prank(executor);
        module.supply(bytes32(uint256(1)), 100 * _assetUnit());
        address aToken = _aToken();
        uint256 shares = IERC20(aToken).balanceOf(address(treasury));
        uint256 amount = 100 * _assetUnit();
        uint256 index = IAavePool(POOL).getReserveNormalizedIncome(LINK);
        uint256 expectedScaled = (amount * 1e27 + index / 2) / index;
        uint256 scaled = IAaveToken(aToken).scaledBalanceOf(address(treasury));
        require(scaled >= amount * 1e27 / index && scaled <= expectedScaled, "scaled principal");
        require(shares >= amount - 16 && shares <= amount + 16, "aToken principal");
        require(token.balanceOf(address(treasury)) == beforeCash - 100 * _assetUnit(), "cash delta");
        require(token.allowance(address(treasury), POOL) == 0, "allowance");
        (uint256 collateral, uint256 debt,,,,) = IAavePool(POOL).getUserAccountData(address(treasury));
        require(collateral > 0 && debt == 0, "account collateral");
        vm.warp(block.timestamp + 1 days);
        require(IERC20(aToken).balanceOf(address(treasury)) > shares, "accrual");
    }

    function test_D3_WithdrawThenRefillAndPay() external {
        vm.prank(executor);
        module.supply(bytes32(uint256(1)), 100 * _assetUnit());
        uint256 cash = token.balanceOf(address(treasury));
        vm.prank(executor);
        module.withdraw(bytes32(uint256(2)), 10 * _assetUnit());
        require(token.balanceOf(address(treasury)) == cash + 10 * _assetUnit(), "withdraw delta");
        _safeTx(op1, LINK, abi.encodeWithSignature("transfer(address,uint256)", address(0xD00D), 9980 * _assetUnit()));
        I.PaymentApproval memory ap = _approval(1, 100 * _assetUnit());
        _refill(ap, bytes32(uint256(3)), 90 * _assetUnit());
        _pay(ap, bytes32(uint256(4)));
        require(
            token.balanceOf(vendor) == 100 * _assetUnit() && token.balanceOf(address(op1)) == 10 * _assetUnit(),
            "settlement"
        );
        require(token.allowance(address(treasury), POOL) == 0, "withdraw allowance");
    }

    function test_ActualPoolBorrowAndRepayWithOneUseOwnerGrants() external {
        bytes32 plan = keccak256("fork-only immutable borrow plan");
        vm.expectRevert(E.BorrowNotAuthorized.selector);
        vm.prank(executor);
        module.borrow(plan);
        vm.prank(executor);
        module.supply(bytes32(uint256(1)), 100 * _assetUnit());
        _owner(
            abi.encodeCall(
                module.authorizeBorrow,
                (plan, 10 * _assetUnit(), uint64(block.timestamp + 1 days), 105e16, uint256(type(uint128).max))
            )
        );
        uint256 cash = token.balanceOf(address(treasury));
        vm.prank(executor);
        module.borrow(plan);
        require(token.balanceOf(address(treasury)) == cash + 10 * _assetUnit(), "borrow cash");
        (, uint256 debt,,,, uint256 hf) = IAavePool(POOL).getUserAccountData(address(treasury));
        require(debt > 0 && hf >= 105e16, "borrow account");
        vm.expectRevert(E.BorrowNotAuthorized.selector);
        vm.prank(executor);
        module.borrow(plan);
        bytes32 repayPlan = keccak256("fork-only immutable repay plan");
        _owner(abi.encodeCall(module.authorizeRepay, (repayPlan, 11 * _assetUnit(), uint64(block.timestamp + 1 days))));
        vm.prank(executor);
        module.repay(repayPlan);
        (, debt,,,,) = IAavePool(POOL).getUserAccountData(address(treasury));
        require(debt == 0 && token.allowance(address(treasury), POOL) == 0, "repayment");
    }

    function test_ActualPoolPostBorrowHealthFactorRollsBack() external {
        vm.prank(executor);
        module.supply(bytes32(uint256(1)), 100 * _assetUnit());
        bytes32 plan = bytes32(uint256(1));
        _owner(
            abi.encodeCall(
                module.authorizeBorrow,
                (
                    plan,
                    10 * _assetUnit(),
                    uint64(block.timestamp + 1 days),
                    type(uint256).max,
                    uint256(type(uint128).max)
                )
            )
        );
        vm.expectRevert(E.HealthFactorTooLow.selector);
        vm.prank(executor);
        module.borrow(plan);
        (, uint256 debt,,,,) = IAavePool(POOL).getUserAccountData(address(treasury));
        require(debt == 0, "failed borrow left debt");
        (,,,, bool used) = module.borrowAuthorizations(plan);
        require(!used, "failed grant consumed");
    }
}
