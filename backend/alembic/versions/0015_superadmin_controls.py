"""add global superadmin controls

Revision ID: 0015_superadmin_controls
Revises: 0014_user_wallpaper_url
Create Date: 2026-06-19
"""

from alembic import op

revision = "0015_superadmin_controls"
down_revision = "0014_user_wallpaper_url"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_superadmin boolean NOT NULL DEFAULT false;")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active boolean NOT NULL DEFAULT true;")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS deactivated_at timestamptz;")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS deactivated_by_user_id uuid;")
    op.execute("CREATE INDEX IF NOT EXISTS ix_users_is_superadmin ON users (is_superadmin);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_users_is_active ON users (is_active);")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_users_is_active;")
    op.execute("DROP INDEX IF EXISTS ix_users_is_superadmin;")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS deactivated_by_user_id;")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS deactivated_at;")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS is_active;")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS is_superadmin;")
