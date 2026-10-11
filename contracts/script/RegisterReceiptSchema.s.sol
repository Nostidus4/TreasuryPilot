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
        string memory json = vm.serializeBytes32("receipt", "easSchemaUid", uid);
        vm.writeJson(json, "../deployments/11155111.json", "easSchemaUid");
    }
}
