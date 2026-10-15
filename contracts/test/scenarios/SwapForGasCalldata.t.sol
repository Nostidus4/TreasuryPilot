// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {TreasuryFixture} from "../helpers/TreasuryFixture.sol";
import {ITreasuryPilotModule as I} from "../../src/interfaces/ITreasuryPilotModule.sol";
import {TestRouter} from "../../src/test-assets/TestRouter.sol";
import {TestUSDC} from "../../src/test-assets/TestUSDC.sol";

/// @notice EXE-011: the calldata the worker/signer build for a SWAP step runs on the real module.
contract SwapForGasCalldataTest is TreasuryFixture {
    string internal constant VECTOR = "test/vectors/swap-for-gas-calldata.json";

    function test_signerEncodedSwapForGasExecutesOnTheTestRouter() external {
        TestUSDC output = new TestUSDC();
        TestRouter router = new TestRouter(address(token), address(output), 2, 1);
        output.mint(address(router), 1000e6);
        _owner(abi.encodeCall(module.configureSwap, (address(router), address(output), I.Limits(100e6, 150e6))));

        string memory json = vm.readFile(VECTOR);
        bytes memory data = vm.parseJsonBytes(json, ".calldata");
        bytes32 stepId = vm.parseJsonBytes32(json, ".stepId");
        uint256 amountIn = vm.parseJsonUint(json, ".amountIn");
        uint256 minOut = vm.parseJsonUint(json, ".minOut");
        require(
            keccak256(data) == keccak256(abi.encodeCall(module.swapForGas, (stepId, amountIn, minOut))),
            "vector is not the module ABI"
        );

        uint256 cashBefore = token.balanceOf(address(treasury));
        vm.prank(executor);
        (bool ok,) = address(module).call(data);
        require(ok, "swapForGas reverted");
        require(module.stepUsed(stepId), "step not consumed");
        require(output.balanceOf(address(treasury)) == 200e6, "swap output");
        require(token.balanceOf(address(treasury)) == cashBefore - amountIn, "swap input");
    }
}
