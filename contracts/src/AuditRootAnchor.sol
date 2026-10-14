// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Ownable2Step} from "@openzeppelin/contracts/access/Ownable2Step.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";

/// @notice Stores an organization's verified audit-chain head once per UTC day.
/// @dev `orgId` is the bytes32 encoding of the platform organization UUID. The
///      contract stores no audit data, only the SHA-256 chain head.
contract AuditRootAnchor is Ownable2Step {
    error InvalidOrganization();
    error InvalidPublisher();
    error UnauthorizedPublisher();
    error FutureDay();
    error AlreadyAnchored();

    mapping(bytes32 orgId => address publisher) public publisherOf;
    mapping(bytes32 orgId => mapping(uint64 utcDay => bytes32 root)) public rootAt;

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

    /// @notice Anchor a root for a UTC day, once. Past days may be backfilled.
    function anchorRoot(bytes32 orgId, uint64 utcDay, bytes32 root) external {
        if (msg.sender != publisherOf[orgId] || msg.sender == address(0)) {
            revert UnauthorizedPublisher();
        }
        if (orgId == bytes32(0) || root == bytes32(0)) revert InvalidOrganization();
        if (utcDay > block.timestamp / 1 days) revert FutureDay();
        if (rootAt[orgId][utcDay] != bytes32(0)) revert AlreadyAnchored();

        rootAt[orgId][utcDay] = root;
        emit RootAnchored(orgId, utcDay, root);
    }
}
