// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {ISafeWallet, ISafeProxyFactory} from "../../src/interfaces/ISafeWallet.sol";
import {Vm} from "./Vm.sol";

abstract contract SafeTestHelper {
    Vm internal constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));

    // Deploy official pinned artifacts without compiling Safe 1.4.1 via IR.
    function deployOneOfOneSafe(address owner, uint256 saltNonce) internal returns (ISafeWallet safe) {
        address singleton = _deployArtifact("Safe.sol:Safe");
        ISafeProxyFactory factory = ISafeProxyFactory(_deployArtifact("SafeProxyFactory.sol:SafeProxyFactory"));
        address[] memory owners = new address[](1);
        owners[0] = owner;
        bytes memory initializer = abi.encodeCall(
            ISafeWallet.setup, (owners, 1, address(0), bytes(""), address(0), address(0), 0, payable(address(0)))
        );
        safe = ISafeWallet(factory.createProxyWithNonce(singleton, initializer, saltNonce));
    }

    function _deployArtifact(string memory artifact) internal returns (address deployed) {
        bytes memory code = vm.getCode(artifact);
        assembly ("memory-safe") { deployed := create(0, add(code, 32), mload(code)) }
        require(deployed != address(0), "artifact deployment failed");
    }

    function approvedHashSignature(address owner) internal pure returns (bytes memory) {
        return abi.encodePacked(bytes32(uint256(uint160(owner))), bytes32(0), uint8(1));
    }
}
