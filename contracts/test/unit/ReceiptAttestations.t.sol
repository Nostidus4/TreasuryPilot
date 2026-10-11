// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {IReceiptSchemaRegistry, IReceiptEAS} from "../../src/interfaces/IReceiptEAS.sol";
import {MockReceiptSchemaRegistry, MockReceiptEAS} from "../../src/test-assets/MockReceiptEAS.sol";
import {ReceiptSchema} from "../../script/ReceiptSchema.sol";

contract ReceiptAttestationsTest {
    function testReceiptSchemaAndStaticTupleResolveLocally() external {
        MockReceiptSchemaRegistry registry = new MockReceiptSchemaRegistry();
        MockReceiptEAS eas = new MockReceiptEAS(address(registry));
        bytes32 schemaUid = ReceiptSchema.register(address(registry));
        require(schemaUid == ReceiptSchema.uid(), "schema UID");
        require(ReceiptSchema.register(address(registry)) == schemaUid, "idempotent registration");
        IReceiptSchemaRegistry.SchemaRecord memory record = registry.getSchema(schemaUid);
        require(record.resolver == address(0) && !record.revocable, "non-revocable schema");
        require(
            keccak256(bytes(record.schema))
                == keccak256(
                    bytes(
                        "bytes32 requestId,bytes32 invoiceHash,bytes32 approvalHash,bytes32 planHash,bytes32 payTxHash,address payee,uint256 amount,bytes32 policyVersion"
                    )
                ),
            "schema order"
        );

        bytes memory data = abi.encode(
            bytes32(uint256(1)),
            bytes32(uint256(2)),
            bytes32(uint256(3)),
            bytes32(uint256(4)),
            bytes32(uint256(5)),
            address(0xBEEF),
            uint256(9007199254740993000000),
            bytes32(uint256(7))
        );
        IReceiptEAS.AttestationRequest memory request = IReceiptEAS.AttestationRequest({
            schema: schemaUid,
            data: IReceiptEAS.AttestationRequestData({
                recipient: address(0xBEEF),
                expirationTime: 0,
                revocable: false,
                refUID: bytes32(0),
                data: data,
                value: 0
            })
        });
        bytes32 uid = eas.attest(request);
        require(keccak256(eas.receipts(uid)) == keccak256(data), "EAS receipt bytes");
    }

    function testMockRejectsRevocationExpiryAndUnknownSchema() external {
        MockReceiptSchemaRegistry registry = new MockReceiptSchemaRegistry();
        MockReceiptEAS eas = new MockReceiptEAS(address(registry));
        IReceiptEAS.AttestationRequest memory request = IReceiptEAS.AttestationRequest({
            schema: bytes32(uint256(77)),
            data: IReceiptEAS.AttestationRequestData({
                recipient: address(0xBEEF),
                expirationTime: 1,
                revocable: true,
                refUID: bytes32(0),
                data: new bytes(256),
                value: 0
            })
        });
        (bool success,) = address(eas).call(abi.encodeCall(eas.attest, (request)));
        require(!success, "unknown schema/revocable receipt accepted");
    }
}
