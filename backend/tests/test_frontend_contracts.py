import json
import uuid

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api.routes.channels import get_channel as get_channel_route
from app.api.routes.channels import list_channels as list_channels_route
from app.core.errors import AppError
from app.db.models import User
from app.main import handle_app_error, handle_http_error
from app.schemas.channels import ChannelCreateRequest
from app.services.channel_service import ChannelService
from tests.test_utils import DummyAMQP


def _dummy_request() -> Request:
    async def receive():
        return {"type": "http.request"}

    return Request({"type": "http", "method": "GET", "path": "/", "headers": []}, receive)


@pytest.mark.asyncio
async def test_get_channels_and_get_channel_include_my_role_and_permissions(db_session):
    owner = User(username="owner_contract", email="owner_contract@example.com", password_hash="x")
    outsider = User(username="outsider_contract", email="outsider_contract@example.com", password_hash="x")
    db_session.add_all([owner, outsider])
    await db_session.commit()
    await db_session.refresh(owner)
    await db_session.refresh(outsider)

    channel = await ChannelService.create_channel(
        db_session,
        owner.id,
        ChannelCreateRequest(name="contract", visibility="public", join_mode="open"),
        DummyAMQP(),
    )

    channels = await list_channels_route(db_session, outsider, None, 50, scope="discover")
    row = next(item for item in channels.items if item.id == channel.id)
    assert row.my_role == "none"
    assert row.permissions.can_publish is False
    assert row.permissions.can_edit_channel is False

    owner_view = await get_channel_route(channel.id, db_session, owner)
    assert owner_view.my_role == "owner"
    assert owner_view.permissions.can_invite is True
    assert owner_view.permissions.can_delete_channel is True


@pytest.mark.asyncio
async def test_error_response_shape_for_forbidden_and_not_found():
    request = _dummy_request()

    forbidden = await handle_app_error(request, AppError("forbidden", 403, code="FORBIDDEN"))
    forbidden_payload = json.loads(forbidden.body.decode("utf-8"))
    assert forbidden_payload == {"code": "FORBIDDEN", "message": "forbidden", "details": None}

    not_found_exc = HTTPException(
        status_code=404,
        detail={"code": "CHANNEL_NOT_FOUND", "message": "channel not found", "details": {"channel_id": str(uuid.uuid4())}},
    )
    not_found = await handle_http_error(request, not_found_exc)
    not_found_payload = json.loads(not_found.body.decode("utf-8"))
    assert not_found_payload["code"] == "CHANNEL_NOT_FOUND"
    assert not_found_payload["message"] == "channel not found"
    assert "channel_id" in not_found_payload["details"]
