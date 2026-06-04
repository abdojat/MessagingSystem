"""enforce safe routing-key identifiers

Revision ID: 0011_safe_routing_key_identifiers
Revises: 0010_admin_can_edit_channel_permission
Create Date: 2026-06-04
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0011_safe_routing_key_identifiers"
down_revision = "0010_admin_can_edit_channel_permission"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_username_no_spaces;")
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT ck_users_username_safe_identifier "
        "CHECK (username ~ '^[A-Za-z0-9_-]{3,50}$');"
    )
    op.execute("ALTER TABLE channels DROP CONSTRAINT IF EXISTS ck_channels_slug_no_spaces;")
    op.execute(
        "ALTER TABLE channels ADD CONSTRAINT ck_channels_slug_safe_identifier "
        "CHECK (channel_slug ~ '^[A-Za-z0-9_-]{3,50}$');"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE channels DROP CONSTRAINT IF EXISTS ck_channels_slug_safe_identifier;")
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_username_safe_identifier;")
    op.execute("ALTER TABLE users ADD CONSTRAINT ck_users_username_no_spaces CHECK (position(' ' in username) = 0);")
    op.execute("ALTER TABLE channels ADD CONSTRAINT ck_channels_slug_no_spaces CHECK (position(' ' in channel_slug) = 0);")
