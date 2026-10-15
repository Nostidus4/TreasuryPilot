// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;
import {TreasuryFixture} from "../helpers/TreasuryFixture.sol";
import {TestUSDC} from "../../src/test-assets/TestUSDC.sol";
import {ITreasuryPilotModule as I} from "../../src/interfaces/ITreasuryPilotModule.sol";
import {TreasuryPilotErrors as E} from "../../src/libraries/TreasuryPilotErrors.sol";

contract AdversarialToken is TestUSDC {
    uint8 public mode;
    address public callback;
    bytes public callbackData;
    bool public callbackSucceeded;

    function setMode(uint8 mode_) external {
        mode = mode_;
    }

    function setCallback(address target, bytes calldata data) external {
        callback = target;
        callbackData = data;
    }

    function execute(address target, bytes calldata data) external {
        (bool ok, bytes memory reason) = target.call(data);
        if (!ok) {
            assembly ("memory-safe") { revert(add(reason, 32), mload(reason)) }
        }
    }

    function transfer(address to, uint256 amount) public override returns (bool) {
        if (mode == 1) return false;
        if (mode == 2) {
            _transfer(msg.sender, to, amount - 1);
            _burn(msg.sender, 1);
            return true;
        }
        if (mode == 3) {
            _transfer(msg.sender, to, amount);
            _burn(msg.sender, 1);
            return true;
        }
        if (mode == 4) (callbackSucceeded,) = callback.call(callbackData);
        if (mode == 5) {
            _transfer(msg.sender, to, amount);
            assembly ("memory-safe") { return(0, 0) }
        }
        return super.transfer(to, amount);
    }
}

contract MaliciousTokenTest is TreasuryFixture {
    function _createToken() internal override returns (TestUSDC) {
        return new AdversarialToken();
    }

    function testFalseReturningTokenRevertsWithoutConsumingRequestOrCounters() external {
        AdversarialToken(address(token)).setMode(1);
        I.PaymentApproval memory ap = _approval(1, 100e6);
        _expectPayError(ap, E.TransferFailed.selector);
        _assertUnchanged(ap);
    }

    function testFeeOnTransferTokenRevertsAndRollsBackBothBalances() external {
        AdversarialToken(address(token)).setMode(2);
        I.PaymentApproval memory ap = _approval(1, 100e6);
        _expectPayError(ap, E.BalanceDeltaMismatch.selector);
        _assertUnchanged(ap);
    }

    function testExtraSenderDebitCannotBypassPostTransferFloor() external {
        AdversarialToken(address(token)).setMode(3);
        I.PaymentApproval memory ap = _approval(1, 100e6);
        _expectPayError(ap, E.BalanceDeltaMismatch.selector);
        _assertUnchanged(ap);
    }

    function testTokenWithNoReturnDataStillMustProduceExactDeltas() external {
        AdversarialToken(address(token)).setMode(5);
        _pay(_approval(1, 100e6), bytes32(uint256(1)));
        require(token.balanceOf(vendor) == 100e6, "no-return token");
    }

    function testExecutorTokenCannotReenterPaymentOrOwnerGovernance() external {
        AdversarialToken evil = AdversarialToken(address(token));
        config.executor = address(evil);
        _owner(abi.encodeCall(module.configureMandate, (config)));
        I.PaymentApproval memory outer = _approval(1, 100e6);
        I.PaymentApproval memory inner = _approval(2, 100e6);
        evil.setCallback(
            address(module), abi.encodeCall(module.pay, (inner, _sign(inner), bytes32(uint256(2)), inner.amount))
        );
        evil.setMode(4);
        evil.execute(
            address(module), abi.encodeCall(module.pay, (outer, _sign(outer), bytes32(uint256(1)), outer.amount))
        );
        require(!evil.callbackSucceeded() && !module.requestPaid(inner.requestId), "reentrant payment");
        require(token.balanceOf(vendor) == 100e6 && module.usedToday(module.PAY()) == 100e6, "outer payment");
    }

    function _assertUnchanged(I.PaymentApproval memory ap) internal view {
        require(!module.requestPaid(ap.requestId) && !module.stepUsed(keccak256("rejected step")), "replay rollback");
        require(module.usedToday(module.PAY()) == 0 && token.balanceOf(vendor) == 0, "payment rollback");
        require(token.balanceOf(address(op1)) == 10000e6, "sender rollback");
    }
}
