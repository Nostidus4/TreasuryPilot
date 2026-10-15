// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Safe} from "@safe-global/safe-contracts/contracts/Safe.sol";
import {SafeProxyFactory} from "@safe-global/safe-contracts/contracts/proxies/SafeProxyFactory.sol";
import {
    CompatibilityFallbackHandler
} from "@safe-global/safe-contracts/contracts/handler/CompatibilityFallbackHandler.sol";
import {MultiSendCallOnly} from "@safe-global/safe-contracts/contracts/libraries/MultiSendCallOnly.sol";

/// @notice Compile-time artifact bundle for the isolated Safe deployment fixture.
/// @dev Keep separate from the module fixture because Safe contracts compile without via-IR.
contract SafeArtifactBundle {
    function deploy() external {
        new Safe();
        new SafeProxyFactory();
        new CompatibilityFallbackHandler();
        new MultiSendCallOnly();
    }
}
