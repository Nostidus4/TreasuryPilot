// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;
import {IReceiptSchemaRegistry, IReceiptEAS} from "../interfaces/IReceiptEAS.sol";

/// @notice Local-only ABI smoke double, not an EAS deployment or trust substitute.
contract MockReceiptSchemaRegistry is IReceiptSchemaRegistry {
    mapping(bytes32 => SchemaRecord) private schemas;

    function register(string calldata schema, address resolver, bool revocable) external returns (bytes32 uid) {
        uid = keccak256(abi.encodePacked(schema, resolver, revocable));
        require(schemas[uid].uid == bytes32(0), "schema already exists");
        schemas[uid] = SchemaRecord(uid, resolver, revocable, schema);
    }

    function getSchema(bytes32 uid) external view returns (SchemaRecord memory) {
        return schemas[uid];
    }
}

contract MockReceiptEAS is IReceiptEAS {
    IReceiptSchemaRegistry public immutable registry;
    mapping(bytes32 => bytes) public receipts;
    mapping(bytes32 => Attestation) private attestations;
    event Attested(address indexed recipient, address indexed attester, bytes32 uid, bytes32 indexed schemaUID);

    constructor(address registry_) {
        registry = IReceiptSchemaRegistry(registry_);
    }

    function attest(AttestationRequest calldata request) external payable returns (bytes32 uid) {
        require(registry.getSchema(request.schema).uid != 0, "unknown schema");
        require(!request.data.revocable && request.data.expirationTime == 0 && request.data.refUID == 0, "receipt mode");
        require(msg.value == 0 && request.data.value == 0 && request.data.data.length == 256, "receipt data");
        uid = keccak256(abi.encode(request, msg.sender, block.timestamp));
        receipts[uid] = request.data.data;
        attestations[uid] = Attestation(
            uid,
            request.schema,
            uint64(block.timestamp),
            0,
            0,
            bytes32(0),
            request.data.recipient,
            msg.sender,
            false,
            request.data.data
        );
        emit Attested(request.data.recipient, msg.sender, uid, request.schema);
    }

    function getAttestation(bytes32 uid) external view returns (Attestation memory) {
        return attestations[uid];
    }
}
