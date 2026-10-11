// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;
import {PaymentApprovalHash} from "../../src/libraries/PaymentApprovalHash.sol";
import {ITreasuryPilotModule} from "../../src/interfaces/ITreasuryPilotModule.sol";

contract PaymentApprovalTypeHashTest {
    function test13FieldTypeHashMatchesIndependentKeccakVector() external pure {
        // Independently computed with Node keccak, not with the Solidity helper.
        require(PaymentApprovalHash.TYPEHASH == 0x87265570230a24bd6f95ca8117865af42d4e1c7820635d83c7abba2b80e20975, "type hash drift");
    }
    function testEarlyOptionFieldsAreIncludedInStructHash() external pure {
        ITreasuryPilotModule.PaymentApproval memory ap;
        bytes32 original = PaymentApprovalHash.structHash(ap);
        ap.earlyAmount = 1;
        require(original != PaymentApprovalHash.structHash(ap), "early amount omitted");
        bytes32 amountChanged = PaymentApprovalHash.structHash(ap);
        ap.earlyPayBy = 1;
        require(amountChanged != PaymentApprovalHash.structHash(ap), "early date omitted");
    }
}
