// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {ITreasuryPilotModule as I} from "../src/interfaces/ITreasuryPilotModule.sol";
import {ITreasuryPilotModuleFactory} from "../src/interfaces/ITreasuryPilotModuleFactory.sol";
import {ISafeWallet, ISafeProxyFactory} from "../src/interfaces/ISafeWallet.sol";
import {Safe} from "@safe-global/safe-contracts/contracts/Safe.sol";
import {SafeProxyFactory} from "@safe-global/safe-contracts/contracts/proxies/SafeProxyFactory.sol";
import {MultiSend} from "@safe-global/safe-contracts/contracts/libraries/MultiSend.sol";
import {SafeTestHelper} from "../test/helpers/SafeTestHelper.sol";
import {Enum} from "@safe-global/safe-contracts/contracts/common/Enum.sol";
import {TestUSDC} from "../src/test-assets/TestUSDC.sol";
import {MockReceiptSchemaRegistry, MockReceiptEAS} from "../src/test-assets/MockReceiptEAS.sol";
import {ReceiptSchema} from "./ReceiptSchema.sol";

/// @notice Test-network deploy, using versioned CREATE2 salts for core bytecode.
contract Deploy is SafeTestHelper {
    bytes32 internal constant IMPLEMENTATION_SALT = keccak256("TreasuryPilot.module.v1");
    bytes32 internal constant FACTORY_SALT = keccak256("TreasuryPilot.factory.v1");
    bytes32 internal constant TOKEN_SALT = keccak256("TreasuryPilot.tUSDC.v1");

    address internal implementation;
    ITreasuryPilotModuleFactory internal factory;
    I internal module;
    TestUSDC internal testToken;
    ISafeWallet internal treasury;
    ISafeWallet internal op1;
    ISafeWallet internal op2;
    address internal asset;
    address internal pool;
    address internal multisend;
    address internal safeSingleton;
    address internal safeProxyFactory;
    address internal owner;
    address internal eas;
    address internal registry;
    bytes32 internal schemaUid;

    function run() external {
        require(block.chainid == 31337 || block.chainid == 11155111, "Anvil/Sepolia only");
        owner = vm.envAddress("DEMO_OWNER");
        require(owner != address(0), "owner required");
        address executor = vm.envAddress("DEMO_EXECUTOR");
        address approver = vm.envAddress("DEMO_APPROVER");
        address guardian = vm.envAddress("DEMO_GUARDIAN");
        address vendor = vm.envAddress("DEMO_PAYEE");

        vm.startBroadcast();
        implementation = _create2(IMPLEMENTATION_SALT, vm.getCode("TreasuryPilotModule.sol:TreasuryPilotModule"));
        factory = ITreasuryPilotModuleFactory(
            _create2(
                FACTORY_SALT,
                abi.encodePacked(
                    vm.getCode("TreasuryPilotModuleFactory.sol:TreasuryPilotModuleFactory"), abi.encode(implementation)
                )
            )
        );
        testToken = TestUSDC(_create2(TOKEN_SALT, vm.getCode("TestUSDC.sol:TestUSDC")));

        if (block.chainid == 31337) {
            asset = address(testToken);
            pool = address(0);
            registry = address(new MockReceiptSchemaRegistry());
            eas = address(new MockReceiptEAS(registry));
        } else {
            asset = 0x94a9D9AC8a22534E3FaCa9F4e7F2E2cf85d5E4C8;
            pool = 0x6Ae43d3271ff6888e7Fc43Fd7321a503ff738951;
            registry = 0x0a7E2Ff54e76B8E6659aedc9103FB21c038050D0;
            eas = 0xC2679fBD37d54388Ce493F1DB75320D236e1815e;
            require(asset.code.length != 0 && pool.code.length != 0 && eas.code.length != 0, "Sepolia config missing");
        }
        schemaUid = ReceiptSchema.register(registry);

        Safe singleton = new Safe();
        SafeProxyFactory safeFactory = new SafeProxyFactory();
        safeSingleton = address(singleton);
        safeProxyFactory = address(safeFactory);
        ISafeProxyFactory proxyFactory = ISafeProxyFactory(address(safeFactory));
        treasury = _newSafe(singleton, proxyFactory, owner, 1);
        op1 = _newSafe(singleton, proxyFactory, owner, 2);
        op2 = _newSafe(singleton, proxyFactory, owner, 3);
        MultiSend multi = new MultiSend();
        multisend = address(multi);

        _setup(executor, approver, guardian, vendor);
        if (block.chainid == 31337) {
            testToken.mint(address(treasury), 30000e6);
            testToken.mint(address(op1), 100e6);
            testToken.mint(address(op2), 100e6);
        }
        vm.stopBroadcast();
        _manifest();
    }

    function _create2(bytes32 salt, bytes memory code) internal returns (address deployed) {
        deployed = address(
            uint160(
                uint256(
                    keccak256(
                        abi.encodePacked(
                            bytes1(0xff), 0x4e59b44847b379578588920cA78FbF26c0B4956C, salt, keccak256(code)
                        )
                    )
                )
            )
        );
        if (deployed.code.length != 0) return deployed;
        (bool success,) = 0x4e59b44847b379578588920cA78FbF26c0B4956C.call(bytes.concat(salt, code));
        require(success && deployed.code.length != 0, "CREATE2 deployment failed");
    }

    function _newSafe(Safe singleton, ISafeProxyFactory proxyFactory, address safeOwner, uint256 saltNonce)
        internal
        returns (ISafeWallet)
    {
        address[] memory owners = new address[](1);
        owners[0] = safeOwner;
        bytes memory initializer = abi.encodeCall(
            ISafeWallet.setup, (owners, 1, address(0), bytes(""), address(0), address(0), 0, payable(address(0)))
        );
        return ISafeWallet(proxyFactory.createProxyWithNonce(address(singleton), initializer, saltNonce));
    }

    function _setup(address executor, address approver, address guardian, address vendor) internal {
        address[] memory operational = new address[](2);
        operational[0] = address(op1);
        operational[1] = address(op2);
        address[] memory approvers = new address[](1);
        approvers[0] = approver;
        I.BufferInit[] memory buffers = new I.BufferInit[](3);
        buffers[0] = I.BufferInit(address(treasury), 1000e6, 0);
        buffers[1] = I.BufferInit(address(op1), 10e6, 150e6);
        buffers[2] = I.BufferInit(address(op2), 10e6, 150e6);
        I.MandateInit memory m = I.MandateInit(
            uint64(block.timestamp),
            uint64(block.timestamp + 30 days),
            300,
            executor,
            guardian,
            I.Limits(2000e6, 10000e6),
            I.Limits(2500e6, 12000e6),
            14 days,
            I.Limits(pool == address(0) ? 0 : 5000e6, pool == address(0) ? 0 : 20000e6)
        );

        // The immutable factory constructor performs no CREATE; first clone nonce is 1.
        module = I(address(uint160(uint256(keccak256(abi.encodePacked(hex"d694", address(factory), hex"01"))))));
        bytes memory batch = bytes.concat(
            _call(address(factory), abi.encodeCall(factory.create, (asset, operational, m, approvers, buffers, pool))),
            _call(address(treasury), abi.encodeCall(ISafeWallet.enableModule, (address(module)))),
            _call(address(module), abi.encodeCall(module.addPayee, (vendor)))
        );
        _batch(treasury, batch);
        _batch(op1, _call(address(op1), abi.encodeCall(ISafeWallet.enableModule, (address(module)))));
        _batch(op2, _call(address(op2), abi.encodeCall(ISafeWallet.enableModule, (address(module)))));
        require(
            treasury.isModuleEnabled(address(module)) && op1.isModuleEnabled(address(module))
                && op2.isModuleEnabled(address(module)),
            "demo enable failed"
        );
    }

    function _call(address target, bytes memory data) internal pure returns (bytes memory) {
        return abi.encodePacked(uint8(0), target, uint256(0), uint256(data.length), data);
    }

    function _batch(ISafeWallet safe, bytes memory batch) internal {
        require(
            safe.execTransaction(
                multisend,
                0,
                abi.encodeWithSignature("multiSend(bytes)", batch),
                Enum.Operation.DelegateCall,
                0,
                0,
                0,
                address(0),
                payable(address(0)),
                approvedHashSignature(owner)
            ),
            "owner MultiSend failed"
        );
    }

    function _manifest() internal {
        string memory key = "deployment";
        vm.serializeUint(key, "chainId", block.chainid);
        vm.serializeString(key, "deploymentStatus", "deployed");
        vm.serializeAddress(key, "implementation", address(implementation));
        vm.serializeBytes32(key, "implementationCodeHash", address(implementation).codehash);
        vm.serializeAddress(key, "factory", address(factory));
        vm.serializeBytes32(key, "factoryCodeHash", address(factory).codehash);
        vm.serializeAddress(key, "testToken", address(testToken));
        vm.serializeBytes32(key, "testTokenCodeHash", address(testToken).codehash);
        vm.serializeAddress(key, "asset", asset);
        vm.serializeAddress(key, "aavePool", pool);
        vm.serializeAddress(key, "module", address(module));
        vm.serializeBytes32(key, "moduleCodeHash", address(module).codehash);
        vm.serializeAddress(key, "safeT", address(treasury));
        vm.serializeAddress(key, "safeO1", address(op1));
        vm.serializeAddress(key, "safeO2", address(op2));
        vm.serializeBytes32(key, "safeTCodeHash", address(treasury).codehash);
        vm.serializeBytes32(key, "safeO1CodeHash", address(op1).codehash);
        vm.serializeBytes32(key, "safeO2CodeHash", address(op2).codehash);
        vm.serializeAddress(key, "safeSingleton", safeSingleton);
        vm.serializeBytes32(key, "safeSingletonCodeHash", safeSingleton.codehash);
        vm.serializeAddress(key, "safeProxyFactory", safeProxyFactory);
        vm.serializeBytes32(key, "safeProxyFactoryCodeHash", safeProxyFactory.codehash);
        vm.serializeAddress(key, "multiSend", multisend);
        vm.serializeBytes32(key, "multiSendCodeHash", multisend.codehash);
        vm.serializeAddress(key, "eas", eas);
        vm.serializeAddress(key, "easRegistry", registry);
        vm.serializeBytes32(key, "easSchemaUid", schemaUid);
        vm.serializeBool(key, "easSchemaRegistered", true);
        string memory json = vm.serializeBool(key, "localEasMock", block.chainid == 31337);
        vm.writeJson(json, string.concat("../deployments/", vm.toString(block.chainid), ".json"));
    }
}
