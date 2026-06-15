import base64
from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUserDep, DBDep
from app.core.errors import AppError, to_http_exception
from app.db.models import User
from app.schemas.auth import MeResponse
from app.schemas.users import UpdateMeRequest, UserPublicProfile, UserSearchItem, UserSearchResponse
from app.services.message_service import MessageService

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


@router.patch("/me", response_model=MeResponse)
async def update_me(req: UpdateMeRequest, db: DBDep, user: CurrentUserDep) -> MeResponse:
    payload = req.model_dump(exclude_unset=True)
    if not payload:
        return await me(user)

    try:
        if "avatar_url" in payload:
            await MessageService.validate_avatar_upload_reference(db, user.id, payload["avatar_url"])
    except AppError as exc:
        raise to_http_exception(exc) from exc

    for field, value in payload.items():
        setattr(user, field, value)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        message = str(getattr(exc, "orig", exc)).lower()
        if "email" in message and "unique" in message:
            raise to_http_exception(AppError("email already in use", 409, code="CONFLICT")) from exc
        raise to_http_exception(AppError("failed to update profile", 400, code="VALIDATION_ERROR")) from exc

    await db.refresh(user)
    return await me(user)


def _encode_cursor(username: str, user_id: UUID) -> str:
    raw = f"{username.lower()}|{user_id}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8")


def _decode_cursor(cursor: str) -> tuple[str, UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("utf-8")).decode("utf-8")
        username_raw, user_id_raw = raw.split("|", 1)
        return username_raw, UUID(user_id_raw)
    except Exception as exc:
        raise AppError("invalid cursor", 400, code="PAGINATION_INVALID") from exc


@router.get("/users/search", response_model=UserSearchResponse)
async def search_users(
    db: DBDep,
    _: CurrentUserDep,
    q: str = Query(min_length=1, max_length=255),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> UserSearchResponse:
    if not isinstance(q, str):
        raise to_http_exception(AppError("q cannot be empty", 400, code="VALIDATION_ERROR"))
    q_raw = q.strip()
    if not q_raw:
        raise to_http_exception(AppError("q cannot be empty", 400, code="VALIDATION_ERROR"))
    pattern = f"%{q_raw}%"
    stmt = (
        select(User)
        .where(or_(User.username.ilike(pattern), User.display_name.ilike(pattern)))
        .order_by(func.lower(User.username).asc(), User.id.asc())
    )
    if cursor:
        try:
            cursor_username, cursor_user_id = _decode_cursor(cursor)
        except AppError as exc:
            raise to_http_exception(exc) from exc
        stmt = stmt.where(
            or_(
                func.lower(User.username) > cursor_username,
                and_(func.lower(User.username) == cursor_username, User.id > cursor_user_id),
            )
        )
    rows = await db.execute(stmt.limit(limit + 1))
    users = list(rows.scalars().all())
    has_more = len(users) > limit
    page = users[:limit]
    next_cursor = _encode_cursor(page[-1].username, page[-1].id) if has_more and page else None
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
