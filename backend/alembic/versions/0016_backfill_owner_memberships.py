"""backfill owner memberships for existing channels

Revision ID: 0016_backfill_owner_memberships
Revises: 0015_superadmin_controls
Create Date: 2026-08-04
"""

from alembic import op

revision = "0016_backfill_owner_memberships"
down_revision = "0015_superadmin_controls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO channel_memberships (
            channel_id,
            user_id,
            role,
            created_at,
            approved_at,
            updated_at,
            created_by_user_id,
            invited_by_user_id,
            admin_permissions
        )
        SELECT
            channels.id,
            channels.owner_user_id,
            'owner'::membership_role,
            COALESCE(channels.created_at, now()),
            COALESCE(channels.created_at, now()),
            COALESCE(channels.updated_at, channels.created_at, now()),
            channels.owner_user_id,
            NULL,
            NULL
        FROM channels
        WHERE channels.owner_user_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM channel_memberships
              WHERE channel_memberships.channel_id = channels.id
                AND channel_memberships.user_id = channels.owner_user_id
          );
        """
    )


def downgrade() -> None:
    pass
