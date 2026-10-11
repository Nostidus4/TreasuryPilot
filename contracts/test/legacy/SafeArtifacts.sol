// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;
// Compile official Safe bytecode with the legacy pipeline. Tests deploy these
// artifacts via getCode, so Safe never inherits the module's via-IR setting.
import {Safe} from "@safe-global/safe-contracts/contracts/Safe.sol";
import {SafeProxyFactory} from "@safe-global/safe-contracts/contracts/proxies/SafeProxyFactory.sol";

contract SafeArtifacts {
    function deploySafe() external returns (Safe) {
        return new Safe();
    }

    function deployFactory() external returns (SafeProxyFactory) {
        return new SafeProxyFactory();
    }
}
