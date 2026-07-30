"""add can_edit_channel to admin permissions

Revision ID: 0010_admin_edit_channel_perm
Revises: 0009_admin_permissions
Create Date: 2026-04-26
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0010_admin_edit_channel_perm"
down_revision = "0009_admin_permissions"
branch_labels = None
depends_on = None


# Applies this schema revision; Alembic calls it while moving the database schema between revisions.
def upgrade() -> None:
    op.execute(
        """
        UPDATE channel_memberships
        SET admin_permissions = (COALESCE(admin_permissions::jsonb, '{}'::jsonb) || '{"can_edit_channel": false}'::jsonb)::json
        WHERE role = 'admin'
          AND (
              admin_permissions IS NULL
              OR NOT (admin_permissions::jsonb ? 'can_edit_channel')
          );
        """
    )


# Reverts this schema revision; Alembic calls it while moving the database schema between revisions.
def downgrade() -> None:
    op.execute(
        """
        UPDATE channel_memberships
        SET admin_permissions = (admin_permissions::jsonb - 'can_edit_channel')::json
        WHERE role = 'admin'
          AND admin_permissions IS NOT NULL;
        """
    )
