// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

interface IReceiptSchemaRegistry {
    struct SchemaRecord {
        bytes32 uid;
        address resolver;
        bool revocable;
        string schema;
    }
    function register(string calldata schema, address resolver, bool revocable) external returns (bytes32);
    function getSchema(bytes32 uid) external view returns (SchemaRecord memory);
}

interface IReceiptEAS {
    struct AttestationRequestData {
        address recipient;
        uint64 expirationTime;
        bool revocable;
        bytes32 refUID;
        bytes data;
        uint256 value;
    }

    struct AttestationRequest {
        bytes32 schema;
        AttestationRequestData data;
    }
    function attest(AttestationRequest calldata request) external payable returns (bytes32);
}
