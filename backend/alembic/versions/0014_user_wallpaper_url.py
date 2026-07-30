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


# Applies this schema revision; Alembic calls it while moving the database schema between revisions.
def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS wallpaper_url text;")


# Reverts this schema revision; Alembic calls it while moving the database schema between revisions.
def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS wallpaper_url;")
