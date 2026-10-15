// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;
import {PaymentApprovalHash} from "../../src/libraries/PaymentApprovalHash.sol";
import {ITreasuryPilotModule} from "../../src/interfaces/ITreasuryPilotModule.sol";

contract PaymentApprovalTypeHashTest {
    function test14FieldTypeHashMatchesIndependentKeccakVector() external pure {
        // Independently computed with Node keccak, not with the Solidity helper.
        require(
            PaymentApprovalHash.TYPEHASH == 0x6cd66cf2d3ec3cdfde36ef7a0aa9efd451ecb29a89ee3888bb3a329ad4c04541,
            "type hash drift"
        );
    }

    function testEarlyOptionFieldsAreIncludedInStructHash() external pure {
        ITreasuryPilotModule.PaymentApproval memory ap;
        bytes32 original = PaymentApprovalHash.structHash(ap);
        ap.earlyAmount = 1;
        require(original != PaymentApprovalHash.structHash(ap), "early amount omitted");
        bytes32 amountChanged = PaymentApprovalHash.structHash(ap);
        ap.earlyPayBy = 1;
        require(amountChanged != PaymentApprovalHash.structHash(ap), "early date omitted");
        bytes32 dateChanged = PaymentApprovalHash.structHash(ap);
        ap.isFiat = true;
        require(dateChanged != PaymentApprovalHash.structHash(ap), "fiat flag omitted");
    }
}
