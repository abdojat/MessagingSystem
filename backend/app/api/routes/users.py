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


# Implements the me operation; FastAPI calls it to serve the corresponding HTTP or WebSocket flow.
@router.get("/me", response_model=MeResponse)
async def me(user: CurrentUserDep) -> MeResponse:
    return MeResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        wallpaper_url=user.wallpaper_url,
        bio=user.bio,
        is_superadmin=user.is_superadmin,
        is_active=user.is_active,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


# Updates me; FastAPI calls it to serve the corresponding HTTP or WebSocket flow.
@router.patch("/me", response_model=MeResponse)
async def update_me(req: UpdateMeRequest, db: DBDep, user: CurrentUserDep) -> MeResponse:
    payload = req.model_dump(exclude_unset=True)
    # Return early when `not payload` because the remaining work is not applicable.
    if not payload:
        return await me(user)

    # Attempt this operation and handle expected failures in the exception branches below.
    try:
        # Run this conditional step only when `'avatar_url' in payload` is true.
        if "avatar_url" in payload:
            await MessageService.validate_avatar_upload_reference(db, user.id, payload["avatar_url"])
        # Run this conditional step only when `'wallpaper_url' in payload` is true.
        if "wallpaper_url" in payload:
            await MessageService.validate_profile_image_upload_reference(
                db,
                user.id,
                payload["wallpaper_url"],
                label="wallpaper",
            )
    # Handle `AppError` here so this workflow can recover or report the failure consistently.
    except AppError as exc:
        raise to_http_exception(exc) from exc

    # Process each `(field, value)` from `payload.items()` to apply this step to the full collection.
    for field, value in payload.items():
        setattr(user, field, value)

    # Attempt this operation and handle expected failures in the exception branches below.
    try:
        await db.commit()
    # Handle `IntegrityError` here so this workflow can recover or report the failure consistently.
    except IntegrityError as exc:
        await db.rollback()
        message = str(getattr(exc, "orig", exc)).lower()
        # Reject the operation when `'email' in message and 'unique' in message` to keep invalid state from progressing.
        if "email" in message and "unique" in message:
            raise to_http_exception(AppError("email already in use", 409, code="CONFLICT")) from exc
        raise to_http_exception(AppError("failed to update profile", 400, code="VALIDATION_ERROR")) from exc

    await db.refresh(user)
    return await me(user)


# Implements the encode cursor operation; FastAPI calls it to serve the corresponding HTTP or WebSocket flow.
def _encode_cursor(username: str, user_id: UUID) -> str:
    raw = f"{username.lower()}|{user_id}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8")


# Decodes cursor; FastAPI calls it to serve the corresponding HTTP or WebSocket flow.
def _decode_cursor(cursor: str) -> tuple[str, UUID]:
    # Attempt this operation and handle expected failures in the exception branches below.
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("utf-8")).decode("utf-8")
        username_raw, user_id_raw = raw.split("|", 1)
        return username_raw, UUID(user_id_raw)
    # Handle `Exception` here so this workflow can recover or report the failure consistently.
    except Exception as exc:
        raise AppError("invalid cursor", 400, code="PAGINATION_INVALID") from exc


# Searches users; FastAPI calls it to serve the corresponding HTTP or WebSocket flow.
@router.get("/users/search", response_model=UserSearchResponse)
async def search_users(
    db: DBDep,
    _: CurrentUserDep,
    q: str = Query(min_length=1, max_length=255),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> UserSearchResponse:
    # Reject the operation when `not isinstance(q, str)` to keep invalid state from progressing.
    if not isinstance(q, str):
        raise to_http_exception(AppError("q cannot be empty", 400, code="VALIDATION_ERROR"))
    q_raw = q.strip()
    # Reject the operation when `not q_raw` to keep invalid state from progressing.
    if not q_raw:
        raise to_http_exception(AppError("q cannot be empty", 400, code="VALIDATION_ERROR"))
    pattern = f"%{q_raw}%"
    stmt = (
        select(User)
        .where(or_(User.username.ilike(pattern), User.display_name.ilike(pattern)))
        .order_by(func.lower(User.username).asc(), User.id.asc())
    )
    # Run this conditional step only when `cursor` is true.
    if cursor:
        # Attempt this operation and handle expected failures in the exception branches below.
        try:
            cursor_username, cursor_user_id = _decode_cursor(cursor)
        # Handle `AppError` here so this workflow can recover or report the failure consistently.
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


# Retrieves public profile; FastAPI calls it to serve the corresponding HTTP or WebSocket flow.
@router.get("/users/{user_id}", response_model=UserPublicProfile)
async def get_public_profile(user_id: UUID, db: DBDep, _: CurrentUserDep) -> UserPublicProfile:
    user = await db.get(User, user_id)
    # Reject the operation when `not user` to keep invalid state from progressing.
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
