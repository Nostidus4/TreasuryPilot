// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Enum} from "@safe-global/safe-contracts/contracts/common/Enum.sol";
import {ISafeWallet} from "../../src/interfaces/ISafeWallet.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {TestUSDC} from "../../src/test-assets/TestUSDC.sol";
import {SafeTestHelper} from "../helpers/SafeTestHelper.sol";

contract SafeAndTestUSDCTest is SafeTestHelper {
    function testSafeCanTransferTestUSDC() external {
        ISafeWallet safe = deployOneOfOneSafe(address(this), 1);
        TestUSDC token = new TestUSDC();
        address recipient = address(0xBEEF);
        uint256 amount = 125_000_000;
        token.mint(address(safe), amount);

        bytes memory transferCall = abi.encodeCall(IERC20.transfer, (recipient, amount));
        bool success = safe.execTransaction(
            address(token),
            0,
            transferCall,
            Enum.Operation.Call,
            0,
            0,
            0,
            address(0),
            payable(address(0)),
            approvedHashSignature(address(this))
        );

        require(success, "Safe transaction failed");
        require(token.balanceOf(recipient) == amount, "recipient balance mismatch");
        require(token.balanceOf(address(safe)) == 0, "Safe balance mismatch");
    }
}
