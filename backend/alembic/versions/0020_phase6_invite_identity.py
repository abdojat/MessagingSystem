"""Phase 6 immutable invite targets and explicit email verification state.

Revision ID: 0020_phase6_invite_identity
Revises: 0019_phase4_p0_hardening
"""

from alembic import op
import sqlalchemy as sa


revision = "0020_phase6_invite_identity"
down_revision = "0019_phase4_p0_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Canonicalization cannot safely choose an owner if historical data contains
    # case/whitespace-only duplicates. Fail with an actionable migration error
    # instead of silently transferring an authorization identity.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM users
                WHERE email IS NOT NULL
                GROUP BY lower(btrim(email))
                HAVING count(*) > 1
            ) THEN
                RAISE EXCEPTION
                    'cannot normalize user emails: case/whitespace-insensitive duplicates require manual resolution';
            END IF;
        END
        $$
        """
    )
    op.execute("UPDATE users SET email = lower(btrim(email)) WHERE email IS NOT NULL")
    op.execute(
        "UPDATE channel_invites SET invited_email = lower(btrim(invited_email)) WHERE invited_email IS NOT NULL"
    )
    op.create_index(
        "uq_users_email_normalized",
        "users",
        [sa.text("lower(btrim(email))")],
        unique=True,
        postgresql_where=sa.text("email IS NOT NULL"),
    )

    # Preserve existing-account email invitations across the security boundary:
    # resolve their current unambiguous owner once. Invites for addresses with no
    # account remain unresolved and require verified ownership at acceptance.
    op.execute(
        """
        UPDATE channel_invites AS ci
        SET invited_user_id = u.id
        FROM users AS u
        WHERE ci.invited_user_id IS NULL
          AND ci.invited_email IS NOT NULL
          AND u.email IS NOT NULL
          AND lower(btrim(ci.invited_email)) = lower(btrim(u.email))
        """
    )


def downgrade() -> None:
    op.drop_index("uq_users_email_normalized", table_name="users")
    op.drop_column("users", "email_verified_at")
    # Canonicalized email snapshots and immutable invite bindings are retained:
    # erasing them would be lossy and could restore the authorization flaw.
