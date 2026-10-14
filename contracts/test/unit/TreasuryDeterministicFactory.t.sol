// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;
import {TreasuryFixture} from "../helpers/TreasuryFixture.sol";
import {ITreasuryPilotModule as I} from "../../src/interfaces/ITreasuryPilotModule.sol";
import {ISafeWallet} from "../../src/interfaces/ISafeWallet.sol";
import {TreasuryPilotModule} from "../../src/TreasuryPilotModule.sol";
import {TreasuryPilotErrors as E} from "../../src/libraries/TreasuryPilotErrors.sol";

contract TreasuryDeterministicFactoryTest is TreasuryFixture {
    bytes32 internal constant SALT = keccak256("same public demo salt");

    function _create(ISafeWallet safe, bool deterministic) internal returns (TreasuryPilotModule result) {
        address[] memory ops = new address[](1);
        ops[0] = address(op1);
        address[] memory approvers = new address[](1);
        approvers[0] = approver;
        I.BufferInit[] memory buffers = new I.BufferInit[](2);
        buffers[0] = I.BufferInit(address(safe), 900e6, 0);
        buffers[1] = I.BufferInit(address(op1), 10e6, 150e6);
        vm.prank(address(safe));
        if (deterministic) {
            result = TreasuryPilotModule(
                factory.createDeterministic(address(token), ops, config, approvers, buffers, address(pool), SALT)
            );
        } else {
            result = TreasuryPilotModule(factory.create(address(token), ops, config, approvers, buffers, address(pool)));
        }
    }

    function testCreateTrafficCannotChangeThePredictedClone() external {
        address predicted = factory.predictDeterministicAddress(address(treasury), SALT);
        ISafeWallet second = deployOneOfOneSafe(address(this), 4);
        _create(second, false); // The factory already had the fixture clone; now another CREATE consumes its nonce.
        require(factory.predictDeterministicAddress(address(treasury), SALT) == predicted, "nonce changed prediction");
        TreasuryPilotModule actual = _create(treasury, true);
        require(address(actual) == predicted && actual.safeT() == address(treasury), "wrong deterministic identity");
    }

    function testAnotherSafeCannotConsumeTheTreasurySalt() external {
        address predicted = factory.predictDeterministicAddress(address(treasury), SALT);
        ISafeWallet second = deployOneOfOneSafe(address(this), 4);
        TreasuryPilotModule other = _create(second, true);
        require(address(other) != predicted && other.safeT() == address(second), "salt namespace collision");
        TreasuryPilotModule actual = _create(treasury, true);
        require(address(actual) == predicted && actual.safeT() == address(treasury), "treasury salt consumed");
    }

    function testDeterministicCloneCannotBeRecreatedOrReinitialized() external {
        TreasuryPilotModule actual = _create(treasury, true);
        vm.expectRevert(E.AlreadyInitialized.selector);
        _create(treasury, true);
        address[] memory empty = new address[](0);
        I.BufferInit[] memory buffers = new I.BufferInit[](0);
        vm.expectRevert(E.AlreadyInitialized.selector);
        actual.initialize(address(treasury), address(token), empty, config, empty, buffers, address(pool));
    }

    function testDeterministicFactoryRejectsEOA() external {
        address[] memory empty = new address[](0);
        I.BufferInit[] memory buffers = new I.BufferInit[](0);
        vm.expectRevert(E.NotOwner.selector);
        vm.prank(executor);
        factory.createDeterministic(address(token), empty, config, empty, buffers, address(pool), SALT);
    }
}
