"""frontend contract parity and messaging ux tables

Revision ID: 0003_frontend_contract_parity
Revises: 0002_frontend_ready
Create Date: 2026-03-04
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0003_frontend_contract_parity"
down_revision = "0002_frontend_ready"
branch_labels = None
depends_on = None


# Applies this schema revision; Alembic calls it while moving the database schema between revisions.
def upgrade() -> None:
    op.add_column("users", sa.Column("display_name", sa.String(length=128), nullable=True))
    op.add_column("users", sa.Column("avatar_url", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("bio", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))

    op.add_column("channels", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("channels", sa.Column("avatar_url", sa.Text(), nullable=True))
    op.add_column(
        "channels",
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.add_column(
        "channel_memberships",
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.add_column("channel_memberships", sa.Column("invited_by_user_id", postgresql.UUID(as_uuid=True), nullable=True))

    op.add_column("messages", sa.Column("reply_to_message_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("messages", sa.Column("reply_to_seq_id", sa.BigInteger(), nullable=True))
    op.add_column("messages", sa.Column("attachments", sa.JSON(), nullable=True))
    op.add_column("messages", sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("messages", sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))
    op.add_column("messages", sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("messages", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "message_reactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("emoji", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id", "user_id", "emoji", name="uq_message_reactions_message_user_emoji"),
    )
    op.create_index("ix_message_reactions_channel_message", "message_reactions", ["channel_id", "message_id"], unique=False)
    op.create_index("ix_message_reactions_message_id", "message_reactions", ["message_id"], unique=False)
    op.create_index("ix_message_reactions_user_id", "message_reactions", ["user_id"], unique=False)

    op.create_table(
        "pinned_messages",
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pinned_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["pinned_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("channel_id", "message_id"),
    )
    op.create_index("ix_pinned_messages_channel_created", "pinned_messages", ["channel_id", "created_at"], unique=False)

    op.create_table(
        "uploads",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("checksum", sa.String(length=255), nullable=True),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("public_url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_uploads_owner_user_id", "uploads", ["owner_user_id"], unique=False)

    op.add_column("outbox", sa.Column("type", sa.String(length=128), nullable=True))
    op.add_column("outbox", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_outbox_published_at", "outbox", ["published_at"], unique=False)


# Reverts this schema revision; Alembic calls it while moving the database schema between revisions.
def downgrade() -> None:
    op.drop_index("ix_outbox_published_at", table_name="outbox")
    op.drop_column("outbox", "published_at")
    op.drop_column("outbox", "type")

    op.drop_index("ix_uploads_owner_user_id", table_name="uploads")
    op.drop_table("uploads")

    op.drop_index("ix_pinned_messages_channel_created", table_name="pinned_messages")
    op.drop_table("pinned_messages")

    op.drop_index("ix_message_reactions_user_id", table_name="message_reactions")
    op.drop_index("ix_message_reactions_message_id", table_name="message_reactions")
    op.drop_index("ix_message_reactions_channel_message", table_name="message_reactions")
    op.drop_table("message_reactions")

    op.drop_column("messages", "deleted_at")
    op.drop_column("messages", "edited_at")
    op.drop_column("messages", "updated_at")
    op.drop_column("messages", "is_pinned")
    op.drop_column("messages", "attachments")
    op.drop_column("messages", "reply_to_seq_id")
    op.drop_column("messages", "reply_to_message_id")

    op.drop_column("channel_memberships", "invited_by_user_id")
    op.drop_column("channel_memberships", "updated_at")

    op.drop_column("channels", "updated_at")
    op.drop_column("channels", "avatar_url")
    op.drop_column("channels", "description")

    op.drop_column("users", "updated_at")
    op.drop_column("users", "bio")
    op.drop_column("users", "avatar_url")
    op.drop_column("users", "display_name")
