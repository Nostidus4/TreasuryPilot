// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;
import {Enum} from "@safe-global/safe-contracts/contracts/common/Enum.sol";

interface ISafeModuleWallet {
    function execTransactionFromModuleReturnData(address to, uint256 value, bytes memory data, Enum.Operation operation)
        external
        returns (bool success, bytes memory returnData);
    function getOwners() external view returns (address[] memory);
    function getThreshold() external view returns (uint256);
}
