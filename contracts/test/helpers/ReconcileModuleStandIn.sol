// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {IAavePool} from "../../src/interfaces/IAavePool.sol";

/// @notice TEST ONLY. Stands in for TreasuryPilotModule + Safe T in the worker's post-condition
/// Anvil tests: it holds the funds itself (no Safe/EIP-712 setup) but keeps the module's read
/// surface and id semantics: stepUsed[stepId], requestPaid[requestId], usedToday per action and
/// asset, aToken(). Unrestricted callers: never deploy outside tests.
contract ReconcileModuleStandIn {
    uint8 public constant PAY = 1;
    uint8 public constant SUPPLY = 4;

    IERC20 public immutable asset;
    IAavePool public immutable pool;
    address public immutable aToken;
    mapping(bytes32 => bool) public stepUsed;
    mapping(bytes32 => bool) public requestPaid;
    mapping(bytes32 => uint256) private usedOn;

    constructor(IERC20 asset_, IAavePool pool_, address aToken_) {
        asset = asset_;
        pool = pool_;
        aToken = aToken_;
    }

    function usedToday(uint8 action) external view returns (uint256) {
        return usedToday(action, address(asset));
    }

    function usedToday(uint8 action, address asset_) public view returns (uint256) {
        return usedOn[_key(action, asset_)];
    }

    function pay(address to, uint256 amount, bytes32 stepId, bytes32 requestId) external {
        _use(stepId, PAY, amount);
        requestPaid[requestId] = true;
        require(asset.transfer(to, amount), "transfer failed");
    }

    function supply(bytes32 stepId, uint256 amount) external {
        _use(stepId, SUPPLY, amount);
        asset.approve(address(pool), amount);
        pool.supply(address(asset), amount, address(this), 0);
    }

    function withdraw(bytes32 stepId, uint256 amount) external {
        stepUsed[stepId] = true;
        pool.withdraw(address(asset), amount, address(this));
    }

    function _use(bytes32 stepId, uint8 action, uint256 amount) private {
        stepUsed[stepId] = true;
        usedOn[_key(action, address(asset))] += amount;
    }

    function _key(uint8 action, address asset_) private view returns (bytes32) {
        return keccak256(abi.encode(action, asset_, block.timestamp / 1 days));
    }
}
