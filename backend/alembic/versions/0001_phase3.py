"""initial phase3 schema

Revision ID: 0001_phase3
Revises:
Create Date: 2026-03-03
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0001_phase3"
down_revision = None
branch_labels = None
depends_on = None


channel_visibility = sa.Enum("public", "private", name="channel_visibility")
channel_join_mode = sa.Enum("open", "invite_only", "approval_required", name="channel_join_mode")
membership_role = sa.Enum("owner", "admin", "member", "pending", name="membership_role")
content_type = sa.Enum("text", "json", name="content_type")
outbox_status = sa.Enum("pending", "sent", "failed", name="outbox_status")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "channels",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("visibility", channel_visibility, nullable=False),
        sa.Column("join_mode", channel_join_mode, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "user_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("refresh_token_hash", sa.String(length=128), nullable=False),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"], unique=False)
    op.create_index("ix_user_sessions_refresh_token_hash", "user_sessions", ["refresh_token_hash"], unique=False)

    op.create_table(
        "channel_counters",
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("next_seq", sa.BigInteger(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("channel_id"),
    )

    op.create_table(
        "channel_memberships",
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", membership_role, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("channel_id", "user_id"),
    )
    op.create_index("ix_channel_memberships_user_id", "channel_memberships", ["user_id"], unique=False)
    op.create_index("ix_channel_memberships_channel_role", "channel_memberships", ["channel_id", "role"], unique=False)

    op.create_table(
        "channel_invites",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("invited_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("invited_email", sa.String(length=255), nullable=True),
        sa.Column("token", sa.String(length=255), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invited_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_channel_invites_token", "channel_invites", ["token"], unique=True)

    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sender_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seq_id", sa.BigInteger(), nullable=False),
        sa.Column("content_type", content_type, nullable=False),
        sa.Column("content_text", sa.Text(), nullable=True),
        sa.Column("content_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sender_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("channel_id", "seq_id", name="uq_messages_channel_seq"),
    )
    op.create_index("ix_messages_channel_created_at", "messages", ["channel_id", "created_at"], unique=False)
    op.create_index("ix_messages_channel_seq", "messages", ["channel_id", "seq_id"], unique=False)

    op.create_table(
        "user_channel_state",
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("last_seen_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_seen_seq_id", sa.BigInteger(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unread_count", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("channel_id", "user_id"),
    )

    op.create_table(
        "events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"]),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_events_channel_created", "events", ["channel_id", "created_at"], unique=False)
    op.create_index("ix_events_actor_created", "events", ["actor_user_id", "created_at"], unique=False)

    op.create_table(
        "outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("aggregate_type", sa.String(length=64), nullable=False),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("routing_key", sa.String(length=255), nullable=False),
        sa.Column("status", outbox_status, nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_outbox_status_next_retry", "outbox", ["status", "next_retry_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_outbox_status_next_retry", table_name="outbox")
    op.drop_table("outbox")
    op.drop_index("ix_events_actor_created", table_name="events")
    op.drop_index("ix_events_channel_created", table_name="events")
    op.drop_table("events")
    op.drop_table("user_channel_state")
    op.drop_index("ix_messages_channel_seq", table_name="messages")
    op.drop_index("ix_messages_channel_created_at", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_channel_invites_token", table_name="channel_invites")
    op.drop_table("channel_invites")
    op.drop_index("ix_channel_memberships_channel_role", table_name="channel_memberships")
    op.drop_index("ix_channel_memberships_user_id", table_name="channel_memberships")
    op.drop_table("channel_memberships")
    op.drop_table("channel_counters")
    op.drop_index("ix_user_sessions_refresh_token_hash", table_name="user_sessions")
    op.drop_index("ix_user_sessions_user_id", table_name="user_sessions")
    op.drop_table("user_sessions")
    op.drop_table("channels")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")
