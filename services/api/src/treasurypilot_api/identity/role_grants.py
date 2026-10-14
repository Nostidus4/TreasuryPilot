from __future__ import annotations

from treasurypilot_api.identity.models import Membership, MembershipStatus

OIDC_ASSIGNABLE_ROLES = frozenset({"Operator", "Finance", "Auditor"})


def seed_legacy_role_sources(membership: Membership, *, oidc_identity_linked: bool = False) -> None:
    """Preserve rows written by an older app instance during a rolling upgrade."""
    if membership.manual_roles or membership.oidc_roles or membership.scim_roles:
        return
    roles = set(membership.roles)
    if not roles:
        return
    if oidc_identity_linked:
        membership.manual_roles = sorted(roles - OIDC_ASSIGNABLE_ROLES)
        membership.oidc_roles = sorted(roles & OIDC_ASSIGNABLE_ROLES)
    else:
        # A first-time OIDC link does not retroactively turn existing manual grants
        # into provider-managed grants. Preserve them when the next group claim changes.
        membership.manual_roles = sorted(roles)


def recompute_membership_roles(membership: Membership) -> frozenset[str]:
    """Materialize the union of independently managed role sources."""
    roles = frozenset((*membership.manual_roles, *membership.oidc_roles, *membership.scim_roles))
    membership.roles = sorted(roles)
    if not roles:
        membership.status = MembershipStatus.SUSPENDED
    return roles
