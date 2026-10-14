// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {AuditRootAnchor} from "../../src/AuditRootAnchor.sol";
import {Vm} from "../helpers/Vm.sol";

contract AuditRootAnchorTest {
    Vm private constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));
    address private constant OWNER = address(0xA11CE);
    address private constant PUBLISHER = address(0xB0B);
    bytes32 private constant ORG = keccak256("org-1");

    AuditRootAnchor private anchor;

    function setUp() public {
        anchor = new AuditRootAnchor(OWNER);
        vm.prank(OWNER);
        anchor.setPublisher(ORG, PUBLISHER);
    }

    function testAuthorizedPublisherAnchorsExactRootForUtcDay() public {
        uint64 day = uint64(block.timestamp / 1 days);
        bytes32 root = keccak256("audit-head");

        vm.prank(PUBLISHER);
        anchor.anchorRoot(ORG, day, root);

        require(anchor.rootAt(ORG, day) == root, "stored root mismatch");
    }

    function testUnauthorizedPublisherCannotAnchor() public {
        vm.expectRevert(AuditRootAnchor.UnauthorizedPublisher.selector);
        anchor.anchorRoot(ORG, uint64(block.timestamp / 1 days), keccak256("root"));
    }

    function testCannotOverwriteDailyRoot() public {
        uint64 day = uint64(block.timestamp / 1 days);
        vm.prank(PUBLISHER);
        anchor.anchorRoot(ORG, day, keccak256("first"));

        vm.prank(PUBLISHER);
        vm.expectRevert(AuditRootAnchor.AlreadyAnchored.selector);
        anchor.anchorRoot(ORG, day, keccak256("second"));
    }

    function testCannotAnchorFutureDay() public {
        vm.prank(PUBLISHER);
        vm.expectRevert(AuditRootAnchor.FutureDay.selector);
        anchor.anchorRoot(ORG, uint64(block.timestamp / 1 days + 1), keccak256("root"));
    }

    function testCannotAnchorZeroRoot() public {
        vm.prank(PUBLISHER);
        vm.expectRevert(AuditRootAnchor.InvalidOrganization.selector);
        anchor.anchorRoot(ORG, uint64(block.timestamp / 1 days), bytes32(0));
    }
}
