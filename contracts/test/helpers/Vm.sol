// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

/// @notice Minimal pinned cheatcode surface; no unpinned forge-std dependency.
interface Vm {
    function etch(address target, bytes calldata code) external;
    function getCode(string calldata artifact) external view returns (bytes memory);
    function addr(uint256 privateKey) external pure returns (address);
    function sign(uint256 privateKey, bytes32 digest) external pure returns (uint8 v, bytes32 r, bytes32 s);
    function prank(address sender) external;
    function startPrank(address sender) external;
    function stopPrank() external;
    function warp(uint256 timestamp) external;
    function chainId(uint256 newChainId) external;
    function expectRevert(bytes4 selector) external;
    function expectRevert(bytes calldata revertData) external;
    function assume(bool condition) external;
    function deal(address account, uint256 balance) external;
    function readFile(string calldata path) external view returns (string memory);
    function parseJsonBytes32(string calldata json, string calldata key) external pure returns (bytes32);
    function parseJsonUint(string calldata json, string calldata key) external pure returns (uint256);
    function parseJsonAddress(string calldata json, string calldata key) external pure returns (address);
    function parseJsonBytes(string calldata json, string calldata key) external pure returns (bytes memory);
    function createSelectFork(string calldata url, uint256 blockNumber) external returns (uint256);
    function envString(string calldata name) external view returns (string memory);
    function envUint(string calldata name) external view returns (uint256);
    function envOr(string calldata name, string calldata defaultValue) external view returns (string memory);
    function envOr(string calldata name, uint256 defaultValue) external view returns (uint256);
    function load(address target, bytes32 slot) external view returns (bytes32);
    function store(address target, bytes32 slot, bytes32 value) external;
    function startBroadcast(uint256 privateKey) external;
    function stopBroadcast() external;
    function writeJson(string calldata json, string calldata path) external;
    function serializeAddress(string calldata objectKey, string calldata valueKey, address value)
        external
        returns (string memory);
    function serializeUint(string calldata objectKey, string calldata valueKey, uint256 value)
        external
        returns (string memory);
    function serializeBytes32(string calldata objectKey, string calldata valueKey, bytes32 value)
        external
        returns (string memory);
    function serializeBool(string calldata objectKey, string calldata valueKey, bool value)
        external
        returns (string memory);
    function toString(uint256 value) external pure returns (string memory);
}
