// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {TreasuryFixture} from "../helpers/TreasuryFixture.sol";
import {ITreasuryPilotModule as I} from "../../src/interfaces/ITreasuryPilotModule.sol";

/// @notice Contract half of POL-004. Expected outcomes come from the same JSON matrix as pytest.
contract PolicyContractDifferentialTest is TreasuryFixture {
    string internal constant CASES = "test/vectors/policy_contract_differential.json";

    function test_differential_validPay() external {
        _comparePay("valid_pay", _approval(100, 1500e6));
    }

    function test_differential_perRequestCapExact() external {
        _comparePay("cap_exact", _approval(101, 2000e6));
    }

    function test_differential_perRequestCapPlusOne() external {
        _comparePay("cap_plus_one", _approval(102, 2000e6 + 1));
    }

    function test_differential_dailyLimit() external {
        I.PaymentApproval memory ap;
        for (uint256 i; i < 5; ++i) {
            ap = _approval(200 + i, 1998e6);
            _pay(ap, bytes32(200 + i));
        }
        _comparePay("daily_limit", _approval(206, 11e6));
    }

    function test_differential_unknownPayee() external {
        I.PaymentApproval memory ap = _approval(103, 1e6);
        ap.payee = address(0xABCD);
        _comparePay("unknown_payee", ap);
    }

    function test_differential_coolingBeforeEdge() external {
        address newPayee = address(0xBEE1);
        _owner(abi.encodeCall(module.addPayee, (newPayee)));
        I.PaymentApproval memory ap = _approval(104, 1e6);
        ap.payee = newPayee;
        _comparePay("cooling_before_edge", ap);
    }

    function test_differential_coolingAtEdge() external {
        address newPayee = address(0xBEE2);
        _owner(abi.encodeCall(module.addPayee, (newPayee)));
        (, uint64 activeFrom) = module.payeeStatus(newPayee);
        vm.warp(activeFrom);
        I.PaymentApproval memory ap = _approval(105, 1e6);
        ap.payee = newPayee;
        _comparePay("cooling_at_edge", ap);
    }

    function test_differential_pausedMandate() external {
        _owner(abi.encodeCall(module.pause, ()));
        _comparePay("mandate_paused", _approval(106, 1e6));
    }

    function test_differential_expiredApproval() external {
        I.PaymentApproval memory ap = _approval(107, 1e6);
        ap.expiry = uint64(block.timestamp - 1);
        _comparePay("approval_expired", ap);
    }

    function test_differential_refillBound() external {
        I.PaymentApproval memory ap = _approval(108, 100e6);
        _compareRefill("refill_bound", ap, 1e6);
    }

    function test_differential_validException() external {
        I.PaymentApproval memory ap = _approval(109, 2500e6);
        _owner(
            abi.encodeCall(
                module.grantException, (ap.requestId, uint128(ap.amount), ap.payee, uint64(block.timestamp + 1 days))
            )
        );
        _comparePay("valid_exception", ap);
    }

    function test_differential_invalidException() external {
        I.PaymentApproval memory ap = _approval(110, 2500e6);
        _owner(
            abi.encodeCall(
                module.grantException,
                    (ap.requestId, uint128(ap.amount - 1), ap.payee, uint64(block.timestamp + 1 days))
            )
        );
        _comparePay("invalid_exception", ap);
    }

    function test_differential_duplicateBlocked() external {
        I.PaymentApproval memory first = _approval(111, 1e6);
        _pay(first, bytes32(uint256(111)));
        I.PaymentApproval memory duplicate = _approval(112, 1e6);
        duplicate.fingerprint = first.fingerprint;
        _comparePay("duplicate_blocked", duplicate);
    }

    function test_differential_duplicateAllowed() external {
        I.PaymentApproval memory first = _approval(113, 1e6);
        _pay(first, bytes32(uint256(113)));
        I.PaymentApproval memory duplicate = _approval(114, 1e6);
        duplicate.fingerprint = first.fingerprint;
        _owner(abi.encodeCall(module.allowDuplicate, (duplicate.fingerprint, duplicate.requestId)));
        _comparePay("duplicate_allowed", duplicate);
    }

    function _comparePay(string memory caseId, I.PaymentApproval memory ap) internal {
        _compare(caseId, abi.encodeCall(module.pay, (ap, _sign(ap), keccak256(bytes(caseId)))));
    }

    function _compareRefill(string memory caseId, I.PaymentApproval memory ap, uint256 amount) internal {
        _compare(
            caseId,
            abi.encodeCall(module.refill, (ap, _sign(ap), keccak256(bytes(caseId)), ap.payingWallet, amount))
        );
    }

    function _compare(string memory caseId, bytes memory callData) internal {
        string memory json = vm.readFile(CASES);
        string memory root = string.concat(".", caseId);
        bool expectedSuccess = vm.parseJsonBool(json, string.concat(root, ".contract_success"));
        vm.prank(executor);
        (bool success, bytes memory result) = address(module).call(callData);
        require(success == expectedSuccess, string.concat(caseId, ": success mismatch"));
        if (!expectedSuccess) {
            string memory signature = vm.parseJsonString(json, string.concat(root, ".contract_error"));
            bytes4 expected = bytes4(keccak256(bytes(signature)));
            bytes4 actual;
            if (result.length >= 4) {
                assembly {
                    actual := mload(add(result, 32))
                }
            }
            require(actual == expected, string.concat(caseId, ": revert selector mismatch"));
        }
    }
}
