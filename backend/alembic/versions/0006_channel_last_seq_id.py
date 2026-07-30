"""channel last_seq_id and contract indexes

Revision ID: 0006_channel_last_seq_id
Revises: 0005_frontend_safety_indexes
Create Date: 2026-03-05
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0006_channel_last_seq_id"
down_revision = "0005_frontend_safety_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Repair drifted databases that were stamped but never fully initialized.
    if not inspector.has_table("channels"):
        from app.db.models import Base

        Base.metadata.create_all(bind=bind)
        inspector = sa.inspect(bind)

    if inspector.has_table("channels"):
        op.execute("ALTER TABLE channels ADD COLUMN IF NOT EXISTS last_seq_id BIGINT NOT NULL DEFAULT 0;")
        op.execute("UPDATE channels SET last_seq_id = 0 WHERE last_seq_id IS NULL;")

        if inspector.has_table("messages"):
            op.execute(
                """
                UPDATE channels c
                SET last_seq_id = COALESCE(m.max_seq, 0)
                FROM (
                  SELECT channel_id, MAX(seq_id) AS max_seq
                  FROM messages
                  GROUP BY channel_id
                ) m
                WHERE c.id = m.channel_id;
                """
            )

    if inspector.has_table("messages"):
        op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_messages_channel_seq_idx ON messages (channel_id, seq_id);")
    if inspector.has_table("user_channel_state"):
        op.execute("CREATE INDEX IF NOT EXISTS ix_user_channel_state_channel_user ON user_channel_state (channel_id, user_id);")
    if inspector.has_table("pinned_messages"):
        op.execute("CREATE INDEX IF NOT EXISTS ix_pinned_messages_channel ON pinned_messages (channel_id);")
    if inspector.has_table("channel_invites"):
        op.execute("CREATE INDEX IF NOT EXISTS ix_channel_invites_expires_at ON channel_invites (expires_at);")
    if inspector.has_table("message_reactions"):
        op.execute("CREATE INDEX IF NOT EXISTS ix_message_reactions_message_id ON message_reactions (message_id);")
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_message_reactions_message_user_emoji ON message_reactions (message_id, user_id, emoji);"
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_message_reactions_message_user_emoji;")
    op.execute("DROP INDEX IF EXISTS ix_message_reactions_message_id;")
    op.execute("DROP INDEX IF EXISTS ix_channel_invites_expires_at;")
    op.execute("DROP INDEX IF EXISTS ix_pinned_messages_channel;")
    op.execute("DROP INDEX IF EXISTS ix_user_channel_state_channel_user;")
    op.execute("DROP INDEX IF EXISTS uq_messages_channel_seq_idx;")
    op.execute("ALTER TABLE channels DROP COLUMN IF EXISTS last_seq_id;")
