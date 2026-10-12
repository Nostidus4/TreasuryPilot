// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;
import {SafeTestHelper} from "../test/helpers/SafeTestHelper.sol";
import {ReceiptSchema} from "./ReceiptSchema.sol";

contract RegisterReceiptSchema is SafeTestHelper {
    function run() external returns (bytes32 uid) {
        require(block.chainid == 11155111, "Sepolia only");
        vm.startBroadcast();
        uid = ReceiptSchema.register(0x0a7E2Ff54e76B8E6659aedc9103FB21c038050D0);
        vm.stopBroadcast();
        vm.serializeUint("receipt", "chainId", block.chainid);
        vm.serializeAddress("receipt", "easRegistry", 0x0a7E2Ff54e76B8E6659aedc9103FB21c038050D0);
        vm.serializeBool("receipt", "easSchemaRegistered", false);
        string memory json = vm.serializeBytes32("receipt", "easSchemaUid", uid);
        // Prediction only: publish_manifest.py checks real RPC state before updating the manifest.
        vm.writeJson(json, "../deployments/predictions/11155111.schema.json");
    }
}
