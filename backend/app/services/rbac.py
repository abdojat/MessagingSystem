from app.db.models import MembershipRole

APPROVED_ROLES = {MembershipRole.owner, MembershipRole.admin, MembershipRole.member}
ADMIN_PERMISSION_KEYS = (
    "can_publish",
    "can_invite",
    "can_approve",
    "can_manage_members",
    "can_edit_channel",
)
DEFAULT_ADMIN_PERMISSIONS = {
    "can_publish": True,
    "can_invite": True,
    "can_approve": True,
    "can_manage_members": True,
    "can_edit_channel": False,
}


# Normalizes admin permissions; API route handlers call it to enforce application business rules.
def normalize_admin_permissions(raw: dict | None) -> dict[str, bool]:
    # Return early when `not isinstance(raw, dict)` because the remaining work is not applicable.
    if not isinstance(raw, dict):
        return DEFAULT_ADMIN_PERMISSIONS.copy()
    normalized = DEFAULT_ADMIN_PERMISSIONS.copy()
    # Process each `key` from `ADMIN_PERMISSION_KEYS` to apply this step to the full collection.
    for key in ADMIN_PERMISSION_KEYS:
        # Run this conditional step only when `key in raw` is true.
        if key in raw:
            normalized[key] = bool(raw[key])
    return normalized


# Builds permissions; API route handlers call it to enforce application business rules.
def build_permissions(role: MembershipRole | None, admin_permissions: dict | None = None) -> dict[str, bool]:
    # Return early when `role == MembershipRole.owner` because the remaining work is not applicable.
    if role == MembershipRole.owner:
        return {
            "can_publish": True,
            "can_invite": True,
            "can_approve": True,
            "can_manage_members": True,
            "can_edit_channel": True,
            "can_delete_channel": True,
        }
    # Run this conditional step only when `role == MembershipRole.admin` is true.
    if role == MembershipRole.admin:
        admin = normalize_admin_permissions(admin_permissions)
        return {
            "can_publish": admin["can_publish"],
            "can_invite": admin["can_invite"],
            "can_approve": admin["can_approve"],
            "can_manage_members": admin["can_manage_members"],
            "can_edit_channel": admin["can_edit_channel"],
            "can_delete_channel": False,
        }
    return {
        "can_publish": False,
        "can_invite": False,
        "can_approve": False,
        "can_manage_members": False,
        "can_edit_channel": False,
        "can_delete_channel": False,
    }


# Checks whether a membership role may publish messages; API route handlers call it to enforce application business rules.
def can_publish(role: MembershipRole | None, admin_permissions: dict | None = None) -> bool:
    return build_permissions(role, admin_permissions)["can_publish"]


# Checks whether a membership role may create invitations; API route handlers call it to enforce application business rules.
def can_invite(role: MembershipRole | None, admin_permissions: dict | None = None) -> bool:
    return build_permissions(role, admin_permissions)["can_invite"]


# Checks whether a membership role may approve join requests; API route handlers call it to enforce application business rules.
def can_approve(role: MembershipRole | None, admin_permissions: dict | None = None) -> bool:
    return build_permissions(role, admin_permissions)["can_approve"]


# Checks whether a membership role may remove another member; API route handlers call it to enforce application business rules.
def can_remove(actor_role: MembershipRole | None, target_role: MembershipRole | None) -> bool:
    # Return early when `actor_role == MembershipRole.owner` because the remaining work is not applicable.
    if actor_role == MembershipRole.owner:
        return target_role != MembershipRole.owner
    # Return early when `actor_role == MembershipRole.admin` because the remaining work is not applicable.
    if actor_role == MembershipRole.admin:
        return target_role in {MembershipRole.member, MembershipRole.pending}
    return False


# Checks whether a membership role may promote another member; API route handlers call it to enforce application business rules.
def can_promote(actor_role: MembershipRole | None, target_role: MembershipRole | None) -> bool:
    return actor_role == MembershipRole.owner and target_role == MembershipRole.member


# Checks whether a membership role may demote another member; API route handlers call it to enforce application business rules.
def can_demote(actor_role: MembershipRole | None, target_role: MembershipRole | None) -> bool:
    return actor_role == MembershipRole.owner and target_role == MembershipRole.admin


# Checks whether a membership role may read channel data; API route handlers call it to enforce application business rules.
def can_read(role: MembershipRole | None) -> bool:
    return role in APPROVED_ROLES
