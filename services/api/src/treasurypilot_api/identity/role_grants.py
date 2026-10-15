from __future__ import annotations

from treasurypilot_api.identity.models import Membership, MembershipStatus

# SSO/SCIM group claims may grant work roles, never organization ownership, approval,
# guardian, or platform administration privileges.
OIDC_ASSIGNABLE_ROLES = frozenset({"Operator", "Finance", "Auditor"})


def initialize_legacy_role_sources(
    membership: Membership, *, oidc_identity_linked: bool = False
) -> None:
    """Initialize migrated grants once, using OIDC ownership only in its configured tenant."""
    if membership.role_sources_initialized:
        return
    roles = set(membership.roles)
    if oidc_identity_linked:
        membership.manual_roles = sorted(roles - OIDC_ASSIGNABLE_ROLES)
        membership.oidc_roles = sorted(roles & OIDC_ASSIGNABLE_ROLES)
    else:
        membership.manual_roles = sorted(roles)
        membership.oidc_roles = []
    membership.scim_roles = []
    membership.role_sources_initialized = True


def recompute_membership_roles(membership: Membership) -> frozenset[str]:
    """Materialize the union of independently managed role sources."""
    roles = frozenset((*membership.manual_roles, *membership.oidc_roles, *membership.scim_roles))
    membership.roles = sorted(roles)
    if not roles:
        membership.status = MembershipStatus.SUSPENDED
    return roles
