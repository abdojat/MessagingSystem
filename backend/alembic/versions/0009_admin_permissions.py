"""add admin permissions to channel memberships

Revision ID: 0009_admin_permissions
Revises: 0008_channel_slug_no_space_keys
Create Date: 2026-04-25
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0009_admin_permissions"
down_revision = "0008_channel_slug_no_space_keys"
branch_labels = None
depends_on = None


ADMIN_PERMISSIONS_JSON = "{\"can_publish\": true, \"can_invite\": true, \"can_approve\": true, \"can_manage_members\": true}"


# Applies this schema revision; Alembic calls it while moving the database schema between revisions.
def upgrade() -> None:
    op.execute("ALTER TABLE channel_memberships ADD COLUMN IF NOT EXISTS admin_permissions JSON;")
    op.execute(
        f"""
        UPDATE channel_memberships
        SET admin_permissions = '{ADMIN_PERMISSIONS_JSON}'::json
        WHERE role = 'admin' AND (
            admin_permissions IS NULL
            OR admin_permissions::jsonb = '{{}}'::jsonb
        );
        """
    )
    op.execute("UPDATE channel_memberships SET admin_permissions = NULL WHERE role <> 'admin';")


# Reverts this schema revision; Alembic calls it while moving the database schema between revisions.
def downgrade() -> None:
    op.execute("ALTER TABLE channel_memberships DROP COLUMN IF EXISTS admin_permissions;")
