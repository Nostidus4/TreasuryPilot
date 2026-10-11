// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;
import {IReceiptSchemaRegistry} from "../src/interfaces/IReceiptEAS.sol";

library ReceiptSchema {
    string internal constant SCHEMA =
        "bytes32 requestId,bytes32 invoiceHash,bytes32 approvalHash,bytes32 planHash,bytes32 payTxHash,address payee,uint256 amount,bytes32 policyVersion";

    function uid() internal pure returns (bytes32) {
        return keccak256(abi.encodePacked(SCHEMA, address(0), false));
    }

    function register(address registry) internal returns (bytes32 result) {
        require(registry.code.length != 0, "schema registry missing");
        result = uid();
        IReceiptSchemaRegistry r = IReceiptSchemaRegistry(registry);
        IReceiptSchemaRegistry.SchemaRecord memory record = r.getSchema(result);
        if (record.uid == 0) {
            require(r.register(SCHEMA, address(0), false) == result, "schema UID mismatch");
        } else {
            require(
                record.resolver == address(0) && !record.revocable
                    && keccak256(bytes(record.schema)) == keccak256(bytes(SCHEMA)),
                "schema mismatch"
            );
        }
    }
}
