// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Ownable2Step} from "@openzeppelin/contracts/access/Ownable2Step.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";

/// @notice Stores an organization's verified audit-chain head once per UTC day.
/// @dev `orgId` is `keccak256` of the organization UUID's 16 raw bytes (RFC 4122
///      big-endian order, e.g. Python `UUID.bytes`), so no UUID appears on chain. The
///      contract stores no audit data, only the SHA-256 chain head. `anchoredAt` records
///      the block time of each anchor so verifiers can see how late a backfilled day was.
contract AuditRootAnchor is Ownable2Step {
    error InvalidOrganization();
    error UnauthorizedPublisher();
    error FutureDay();
    error AlreadyAnchored();

    mapping(bytes32 orgId => address publisher) public publisherOf;
    mapping(bytes32 orgId => mapping(uint64 utcDay => bytes32 root)) public rootAt;
    mapping(bytes32 orgId => mapping(uint64 utcDay => bool anchored)) public isAnchored;
    mapping(bytes32 orgId => mapping(uint64 utcDay => uint256 timestamp)) public anchoredAt;

    event PublisherSet(bytes32 indexed orgId, address indexed publisher);
    event RootAnchored(bytes32 indexed orgId, uint64 indexed utcDay, bytes32 root);

    constructor(address initialOwner) Ownable(initialOwner) {}

    /// @notice Set the only account permitted to publish an organization's roots.
    /// @dev Set publisher to address(0) to disable publication for the org.
    function setPublisher(bytes32 orgId, address publisher) external onlyOwner {
        if (orgId == bytes32(0)) revert InvalidOrganization();
        publisherOf[orgId] = publisher;
        emit PublisherSet(orgId, publisher);
    }

    /// @notice Anchor a root for a UTC day, once. Past days may be backfilled;
    ///         compare `anchoredAt` with the end of the day to see how late it was.
    function anchorRoot(bytes32 orgId, uint64 utcDay, bytes32 root) external {
        if (msg.sender != publisherOf[orgId]) revert UnauthorizedPublisher();
        if (utcDay > block.timestamp / 1 days) revert FutureDay();
        if (isAnchored[orgId][utcDay]) revert AlreadyAnchored();

        rootAt[orgId][utcDay] = root;
        isAnchored[orgId][utcDay] = true;
        anchoredAt[orgId][utcDay] = block.timestamp;
        emit RootAnchored(orgId, utcDay, root);
    }
}
