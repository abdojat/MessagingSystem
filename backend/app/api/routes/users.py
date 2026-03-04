import base64
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import and_, or_, select

from app.api.deps import CurrentUserDep, DBDep
from app.core.errors import AppError, to_http_exception
from app.db.models import User
from app.schemas.auth import MeResponse
from app.schemas.users import UserPublicProfile, UserSearchItem, UserSearchResponse

router = APIRouter(tags=["users"])


@router.get("/me", response_model=MeResponse)
async def me(user: CurrentUserDep) -> MeResponse:
    return MeResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        bio=user.bio,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


def _encode_cursor(created_at: datetime, user_id: UUID) -> str:
    raw = f"{created_at.isoformat()}|{user_id}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8")


def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("utf-8")).decode("utf-8")
        created_at_raw, user_id_raw = raw.split("|", 1)
        return datetime.fromisoformat(created_at_raw), UUID(user_id_raw)
    except Exception as exc:
        raise AppError("invalid cursor", 422, code="VALIDATION_ERROR") from exc


@router.get("/users/search", response_model=UserSearchResponse)
async def search_users(
    db: DBDep,
    _: CurrentUserDep,
    query: str = Query(min_length=1, max_length=255),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> UserSearchResponse:
    q = f"%{query.strip()}%"
    stmt = (
        select(User)
        .where(or_(User.username.ilike(q), User.display_name.ilike(q)))
        .order_by(User.created_at.desc(), User.id.desc())
    )
    if cursor:
        try:
            cursor_created_at, cursor_user_id = _decode_cursor(cursor)
        except AppError as exc:
            raise to_http_exception(exc) from exc
        stmt = stmt.where(
            or_(
                User.created_at < cursor_created_at,
                and_(User.created_at == cursor_created_at, User.id < cursor_user_id),
            )
        )
    rows = await db.execute(stmt.limit(limit + 1))
    users = list(rows.scalars().all())
    has_more = len(users) > limit
    page = users[:limit]
    next_cursor = _encode_cursor(page[-1].created_at, page[-1].id) if has_more and page else None
    return UserSearchResponse(
        items=[
            UserSearchItem(
                id=u.id,
                username=u.username,
                display_name=u.display_name,
                avatar_url=u.avatar_url,
            )
            for u in page
        ],
        next_cursor=next_cursor,
        has_more=has_more,
    )


@router.get("/users/{user_id}", response_model=UserPublicProfile)
async def get_public_profile(user_id: UUID, db: DBDep, _: CurrentUserDep) -> UserPublicProfile:
    user = await db.get(User, user_id)
    if not user:
        raise to_http_exception(AppError("user not found", 404, code="NOT_FOUND"))
    return UserPublicProfile(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        bio=user.bio,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )
