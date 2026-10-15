// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {ISafeWallet, ISafeProxyFactory} from "../src/interfaces/ISafeWallet.sol";
import {TreasuryPilotModule} from "../src/TreasuryPilotModule.sol";
import {TreasuryPilotModuleFactory} from "../src/TreasuryPilotModuleFactory.sol";
import {TestUSDC} from "../src/test-assets/TestUSDC.sol";
import {Vm} from "../test/helpers/Vm.sol";

/// @notice Deploys the real local contracts used by the treasury setup API integration.
contract SetupWizardFixture {
    Vm private constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));

    function run() external {
        uint256 privateKey = vm.envUint("SETUP_PRIVATE_KEY");
        uint256 saltNonce = vm.envUint("SETUP_SALT_NONCE");
        address owner = vm.addr(privateKey);
        vm.startBroadcast(privateKey);

        address singleton = _deployArtifact("Safe.sol:Safe");
        ISafeProxyFactory safeFactory = ISafeProxyFactory(_deployArtifact("SafeProxyFactory.sol:SafeProxyFactory"));
        address multiSend = _deployArtifact("MultiSendCallOnly.sol:MultiSendCallOnly");
        address fallbackHandler = _deployArtifact("CompatibilityFallbackHandler.sol:CompatibilityFallbackHandler");
        TreasuryPilotModule implementation = new TreasuryPilotModule();
        TreasuryPilotModuleFactory moduleFactory = new TreasuryPilotModuleFactory(address(implementation));
        TestUSDC token = new TestUSDC();
        address safeT = _newSafe(safeFactory, singleton, fallbackHandler, owner, saltNonce);
        address safeO1 = _newSafe(safeFactory, singleton, fallbackHandler, owner, saltNonce + 1);

        vm.stopBroadcast();

        string memory key = "setupWizard";
        vm.serializeAddress(key, "owner", owner);
        vm.serializeAddress(key, "safeSingleton", singleton);
        vm.serializeAddress(key, "safeProxyFactory", address(safeFactory));
        vm.serializeAddress(key, "multiSendCallOnly", multiSend);
        vm.serializeAddress(key, "fallbackHandler", fallbackHandler);
        vm.serializeAddress(key, "moduleImplementation", address(implementation));
        vm.serializeAddress(key, "moduleFactory", address(moduleFactory));
        vm.serializeAddress(key, "token", address(token));
        vm.serializeAddress(key, "safeT", safeT);
        vm.serializeAddress(key, "safeO1", safeO1);
        string memory json = vm.serializeUint(key, "chainId", block.chainid);
        vm.writeJson(json, vm.envString("SETUP_FIXTURE_PATH"));
    }

    function _newSafe(
        ISafeProxyFactory factory,
        address singleton,
        address fallbackHandler,
        address owner,
        uint256 saltNonce
    ) private returns (address) {
        address[] memory owners = new address[](1);
        owners[0] = owner;
        bytes memory initializer = abi.encodeCall(
            ISafeWallet.setup, (owners, 1, address(0), bytes(""), fallbackHandler, address(0), 0, payable(address(0)))
        );
        return factory.createProxyWithNonce(singleton, initializer, saltNonce);
    }

    function _deployArtifact(string memory artifact) private returns (address deployed) {
        bytes memory code = vm.getCode(artifact);
        assembly ("memory-safe") {
            deployed := create(0, add(code, 32), mload(code))
        }
        require(deployed != address(0), "fixture deployment failed");
    }
}
