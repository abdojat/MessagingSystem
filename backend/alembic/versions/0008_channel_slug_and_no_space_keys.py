"""add channel_slug and enforce no-space routing keys

Revision ID: 0008_channel_slug_no_space_keys
Revises: 0007_invite_hash_index
Create Date: 2026-04-12
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0008_channel_slug_no_space_keys"
down_revision = "0007_invite_hash_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("channels"):
        op.execute("ALTER TABLE channels ADD COLUMN IF NOT EXISTS channel_slug VARCHAR(64);")
        op.execute(
            """
            UPDATE channels
            SET channel_slug = CONCAT(
                COALESCE(NULLIF(TRIM(BOTH '-' FROM regexp_replace(lower(COALESCE(name, '')), '[^a-z0-9]+', '-', 'g')), ''), 'channel'),
                '-',
                SUBSTRING(id::text, 1, 8)
            )
            WHERE channel_slug IS NULL OR channel_slug = '';
            """
        )
        op.execute("ALTER TABLE channels ALTER COLUMN channel_slug SET NOT NULL;")
        op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_channels_channel_slug ON channels (channel_slug);")
        op.execute("ALTER TABLE channels DROP CONSTRAINT IF EXISTS ck_channels_slug_no_spaces;")
        op.execute("ALTER TABLE channels ADD CONSTRAINT ck_channels_slug_no_spaces CHECK (position(' ' in channel_slug) = 0);")

    if inspector.has_table("users"):
        op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_username_no_spaces;")
        op.execute("ALTER TABLE users ADD CONSTRAINT ck_users_username_no_spaces CHECK (position(' ' in username) = 0);")


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_username_no_spaces;")
    op.execute("ALTER TABLE channels DROP CONSTRAINT IF EXISTS ck_channels_slug_no_spaces;")
    op.execute("DROP INDEX IF EXISTS uq_channels_channel_slug;")
    op.execute("ALTER TABLE channels DROP COLUMN IF EXISTS channel_slug;")
