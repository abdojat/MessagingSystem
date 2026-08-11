"""Phase 3 attachment authorization relation and quota indexes.

Revision ID: 0018_phase3_abuse_hardening
Revises: 0017_auth_session_hardening
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0018_phase3_abuse_hardening"
down_revision = "0017_auth_session_hardening"
branch_labels = None
depends_on = None


ATTACHMENT_BACKFILL_SQL = """
        INSERT INTO message_attachments (message_id, upload_id, channel_id)
        SELECT m.id, u.id, m.channel_id
        FROM messages AS m
        CROSS JOIN LATERAL jsonb_array_elements(
            CASE
                WHEN jsonb_typeof(m.attachments::jsonb) = 'array'
                THEN m.attachments::jsonb
                ELSE '[]'::jsonb
            END
        ) AS item
        JOIN uploads AS u ON u.id::text = lower(item->>'file_id')
        WHERE item ? 'file_id'
          AND (item->>'file_id') ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
        ON CONFLICT (message_id, upload_id) DO NOTHING
        """


def upgrade() -> None:
    op.create_table(
        "message_attachments",
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("upload_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["upload_id"], ["uploads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("message_id", "upload_id"),
    )
    op.create_index(
        "ix_message_attachments_upload_channel",
        "message_attachments",
        ["upload_id", "channel_id"],
        unique=False,
    )
    op.create_index(
        "ix_message_attachments_channel_message",
        "message_attachments",
        ["channel_id", "message_id"],
        unique=False,
    )
    op.create_index(
        "ix_channel_invites_creator_active",
        "channel_invites",
        ["created_by_user_id", "expires_at"],
        unique=False,
        postgresql_where=sa.text("accepted_at IS NULL AND revoked_at IS NULL"),
    )
    op.create_index(
        "ix_uploads_owner_created_at",
        "uploads",
        ["owner_user_id", "created_at"],
        unique=False,
    )

    # Existing JSON attachments remain the API representation. This normalized
    # relation is an authorization index and is backfilled without trusting
    # malformed historical file ids. SQL JSON null and other scalar/object
    # legacy values are skipped because jsonb_array_elements accepts arrays only.
    op.execute(ATTACHMENT_BACKFILL_SQL)


def downgrade() -> None:
    op.drop_index("ix_uploads_owner_created_at", table_name="uploads")
    op.drop_index("ix_channel_invites_creator_active", table_name="channel_invites")
    op.drop_index("ix_message_attachments_channel_message", table_name="message_attachments")
    op.drop_index("ix_message_attachments_upload_channel", table_name="message_attachments")
    op.drop_table("message_attachments")
