"""bind access authentication to hardened sessions

Revision ID: 0017_auth_session_hardening
Revises: 0016_backfill_owner_memberships
Create Date: 2026-08-10
"""

from alembic import op

revision = "0017_auth_session_hardening"
down_revision = "0016_backfill_owner_memberships"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE user_sessions ADD COLUMN IF NOT EXISTS absolute_expires_at timestamptz;")
    # Existing development sessions receive a one-time 30-day compatibility
    # window. New sessions use the configured absolute lifetime at login.
    op.execute(
        """
        UPDATE user_sessions
        SET absolute_expires_at = GREATEST(expires_at, now() + interval '30 days')
        WHERE absolute_expires_at IS NULL;
        """
    )
    op.execute("ALTER TABLE user_sessions ALTER COLUMN absolute_expires_at SET NOT NULL;")
    op.execute("ALTER TABLE user_sessions ADD COLUMN IF NOT EXISTS replay_detected_at timestamptz;")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_sessions_active_lifetime "
        "ON user_sessions (user_id, revoked_at, expires_at, absolute_expires_at);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_user_sessions_active_lifetime;")
    op.execute("ALTER TABLE user_sessions DROP COLUMN IF EXISTS replay_detected_at;")
    op.execute("ALTER TABLE user_sessions DROP COLUMN IF EXISTS absolute_expires_at;")
