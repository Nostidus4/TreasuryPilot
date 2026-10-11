// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Safe} from "@safe-global/safe-contracts/contracts/Safe.sol";
import {SafeProxy} from "@safe-global/safe-contracts/contracts/proxies/SafeProxy.sol";
import {SafeProxyFactory} from "@safe-global/safe-contracts/contracts/proxies/SafeProxyFactory.sol";

abstract contract SafeTestHelper {
    function deployOneOfOneSafe(address owner, uint256 saltNonce) internal returns (Safe safe) {
        Safe singleton = new Safe();
        SafeProxyFactory factory = new SafeProxyFactory();
        address[] memory owners = new address[](1);
        owners[0] = owner;
        bytes memory initializer = abi.encodeCall(
            Safe.setup, (owners, 1, address(0), bytes(""), address(0), address(0), 0, payable(address(0)))
        );
        SafeProxy proxy = factory.createProxyWithNonce(address(singleton), initializer, saltNonce);
        safe = Safe(payable(address(proxy)));
    }

    function approvedHashSignature(address owner) internal pure returns (bytes memory) {
        return abi.encodePacked(bytes32(uint256(uint160(owner))), bytes32(0), uint8(1));
    }
}
