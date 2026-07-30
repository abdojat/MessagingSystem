"""add user wallpaper url

Revision ID: 0014_user_wallpaper_url
Revises: 0013_event_integrity
Create Date: 2026-06-17
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0014_user_wallpaper_url"
down_revision = "0013_event_integrity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS wallpaper_url text;")


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS wallpaper_url;")
