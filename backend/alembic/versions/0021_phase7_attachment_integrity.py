"""Phase 7 attachment/message channel relational integrity.

Revision ID: 0021_phase7_attachment_integrity
Revises: 0020_phase6_invite_identity
"""

from alembic import op


revision = "0021_phase7_attachment_integrity"
down_revision = "0020_phase6_invite_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Message.channel_id is authoritative. Existing relations already have a
    # single-column message FK, so every row can be normalized unambiguously;
    # no relation is deleted during this repair.
    op.execute(
        """
        UPDATE message_attachments AS ma
        SET channel_id = m.channel_id
        FROM messages AS m
        WHERE m.id = ma.message_id
          AND ma.channel_id IS DISTINCT FROM m.channel_id
        """
    )
    op.create_unique_constraint("uq_messages_id_channel", "messages", ["id", "channel_id"])
    op.drop_constraint("message_attachments_message_id_fkey", "message_attachments", type_="foreignkey")
    op.create_foreign_key(
        "fk_message_attachments_message_channel",
        "message_attachments",
        "messages",
        ["message_id", "channel_id"],
        ["id", "channel_id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_message_attachments_message_channel", "message_attachments", type_="foreignkey")
    op.create_foreign_key(
        "message_attachments_message_id_fkey",
        "message_attachments",
        "messages",
        ["message_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint("uq_messages_id_channel", "messages", type_="unique")
