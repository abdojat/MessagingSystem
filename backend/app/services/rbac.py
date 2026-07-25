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


def normalize_admin_permissions(raw: dict | None) -> dict[str, bool]:
    if not isinstance(raw, dict):
        return DEFAULT_ADMIN_PERMISSIONS.copy()
    normalized = DEFAULT_ADMIN_PERMISSIONS.copy()
    for key in ADMIN_PERMISSION_KEYS:
        if key in raw:
            normalized[key] = bool(raw[key])
    return normalized


def build_permissions(role: MembershipRole | None, admin_permissions: dict | None = None) -> dict[str, bool]:
    if role == MembershipRole.owner:
        return {
            "can_publish": True,
            "can_invite": True,
            "can_approve": True,
            "can_manage_members": True,
            "can_edit_channel": True,
            "can_delete_channel": True,
        }
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


def can_publish(role: MembershipRole | None, admin_permissions: dict | None = None) -> bool:
    return build_permissions(role, admin_permissions)["can_publish"]


def can_invite(role: MembershipRole | None, admin_permissions: dict | None = None) -> bool:
    return build_permissions(role, admin_permissions)["can_invite"]


def can_approve(role: MembershipRole | None, admin_permissions: dict | None = None) -> bool:
    return build_permissions(role, admin_permissions)["can_approve"]


def can_remove(actor_role: MembershipRole | None, target_role: MembershipRole | None) -> bool:
    if actor_role == MembershipRole.owner:
        return target_role != MembershipRole.owner
    if actor_role == MembershipRole.admin:
        return target_role in {MembershipRole.member, MembershipRole.pending}
    return False


def can_promote(actor_role: MembershipRole | None, target_role: MembershipRole | None) -> bool:
    return actor_role == MembershipRole.owner and target_role == MembershipRole.member


def can_demote(actor_role: MembershipRole | None, target_role: MembershipRole | None) -> bool:
    return actor_role == MembershipRole.owner and target_role == MembershipRole.admin


def can_read(role: MembershipRole | None) -> bool:
    return role in APPROVED_ROLES
