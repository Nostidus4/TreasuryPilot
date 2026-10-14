// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;
import {Clones} from "@openzeppelin/contracts/proxy/Clones.sol";
import {TreasuryPilotModule} from "./TreasuryPilotModule.sol";
import {ITreasuryPilotModule} from "./interfaces/ITreasuryPilotModule.sol";
import {ITreasuryPilotModuleFactory} from "./interfaces/ITreasuryPilotModuleFactory.sol";
import {ISafeModuleWallet} from "./interfaces/ISafeModuleWallet.sol";
import {TreasuryPilotErrors as E} from "./libraries/TreasuryPilotErrors.sol";

/// @notice One immutable implementation; each Safe creates its own independent clone.
contract TreasuryPilotModuleFactory is ITreasuryPilotModuleFactory {
    address public immutable implementation;

    constructor(address implementation_) {
        if (implementation_.code.length == 0) revert E.InvalidConfiguration();
        implementation = implementation_;
    }

    /// @inheritdoc ITreasuryPilotModuleFactory
    function create(
        address asset,
        address[] calldata operational,
        ITreasuryPilotModule.MandateInit calldata m,
        address[] calldata approvers,
        ITreasuryPilotModule.BufferInit[] calldata buffers,
        address aavePool
    ) external returns (address module) {
        // No claimed Safe address: the calling Safe transaction is the authority.
        _requireSafeCaller();
        module = Clones.clone(implementation);
        TreasuryPilotModule(module).initialize(msg.sender, asset, operational, m, approvers, buffers, aavePool);
        emit TreasuryModuleCreated(msg.sender, module, asset);
    }

    /// @inheritdoc ITreasuryPilotModuleFactory
    function createDeterministic(
        address asset,
        address[] calldata operational,
        ITreasuryPilotModule.MandateInit calldata m,
        address[] calldata approvers,
        ITreasuryPilotModule.BufferInit[] calldata buffers,
        address aavePool,
        bytes32 salt
    ) external returns (address module) {
        _requireSafeCaller();
        bytes32 scopedSalt = keccak256(abi.encode(msg.sender, salt));
        if (Clones.predictDeterministicAddress(implementation, scopedSalt, address(this)).code.length != 0) {
            revert E.AlreadyInitialized();
        }
        module = Clones.cloneDeterministic(implementation, scopedSalt);
        TreasuryPilotModule(module).initialize(msg.sender, asset, operational, m, approvers, buffers, aavePool);
        emit TreasuryModuleCreated(msg.sender, module, asset);
    }

    /// @inheritdoc ITreasuryPilotModuleFactory
    function predictDeterministicAddress(address safeT, bytes32 salt) external view returns (address module) {
        return Clones.predictDeterministicAddress(implementation, keccak256(abi.encode(safeT, salt)), address(this));
    }

    function _requireSafeCaller() internal view {
        if (msg.sender.code.length == 0) revert E.NotOwner();
        if (ISafeModuleWallet(msg.sender).getThreshold() == 0) revert E.NotOwner();
    }
}
