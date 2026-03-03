from app.db.models import MembershipRole

APPROVED_ROLES = {MembershipRole.owner, MembershipRole.admin, MembershipRole.member}


def can_publish(role: MembershipRole | None) -> bool:
    return role in {MembershipRole.owner, MembershipRole.admin}


def can_invite(role: MembershipRole | None) -> bool:
    return role in {MembershipRole.owner, MembershipRole.admin}


def can_approve(role: MembershipRole | None) -> bool:
    return role in {MembershipRole.owner, MembershipRole.admin}


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
