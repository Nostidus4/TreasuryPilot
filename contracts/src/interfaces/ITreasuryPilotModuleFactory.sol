// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;
import {ITreasuryPilotModule} from "./ITreasuryPilotModule.sol";

interface ITreasuryPilotModuleFactory {
    event TreasuryModuleCreated(address indexed safeT, address indexed module, address asset);
    /// @notice Safe T is msg.sender; clone and initialization are atomic.
    function create(
        address asset,
        address[] calldata operational,
        ITreasuryPilotModule.MandateInit calldata m,
        address[] calldata approvers,
        ITreasuryPilotModule.BufferInit[] calldata buffers,
        address aavePool
    ) external returns (address module);

    /// @notice Safe-scoped CREATE2 salt; another Safe cannot consume this deployment address.
    function createDeterministic(
        address asset,
        address[] calldata operational,
        ITreasuryPilotModule.MandateInit calldata m,
        address[] calldata approvers,
        ITreasuryPilotModule.BufferInit[] calldata buffers,
        address aavePool,
        bytes32 salt
    ) external returns (address module);

    function predictDeterministicAddress(address safeT, bytes32 salt) external view returns (address module);
    function implementation() external view returns (address);
}
