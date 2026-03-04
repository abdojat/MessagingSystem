from fastapi import APIRouter

from app.api.deps import CurrentUserDep
from app.schemas.auth import MeResponse

router = APIRouter(tags=["users"])


@router.get("/me", response_model=MeResponse)
async def me(user: CurrentUserDep) -> MeResponse:
    return MeResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        created_at=user.created_at,
    )
