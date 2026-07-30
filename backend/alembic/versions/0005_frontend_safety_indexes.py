"""frontend safety indexes

Revision ID: 0005_frontend_safety_indexes
Revises: 0004_repair_outbox_schema
Create Date: 2026-03-04
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0005_frontend_safety_indexes"
down_revision = "0004_repair_outbox_schema"
branch_labels = None
depends_on = None


# Applies this schema revision; Alembic calls it while moving the database schema between revisions.
def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_channels_created_id_desc ON channels (created_at DESC, id DESC);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_messages_channel_deleted_seq ON messages (channel_id, deleted_at, seq_id);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_channel_invites_channel_created_id ON channel_invites (channel_id, created_at DESC, id DESC);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_channel_memberships_channel_role_user ON channel_memberships (channel_id, role, user_id);"
    )


# Reverts this schema revision; Alembic calls it while moving the database schema between revisions.
def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_channel_memberships_channel_role_user;")
    op.execute("DROP INDEX IF EXISTS ix_channel_invites_channel_created_id;")
    op.execute("DROP INDEX IF EXISTS ix_messages_channel_deleted_seq;")
    op.execute("DROP INDEX IF EXISTS ix_channels_created_id_desc;")
