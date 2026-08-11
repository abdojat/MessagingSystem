"""Phase 10 provider-backed mailbox verification challenges.

Revision ID: 0023_phase10_email_verification
Revises: 0022_phase9_upload_encryption
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0023_phase10_email_verification"
down_revision = "0022_phase9_upload_encryption"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_verification_challenges",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_email_verification_challenges_token_hash"),
    )
    op.create_index(
        "ix_email_verification_challenges_user_id",
        "email_verification_challenges",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_email_verification_challenges_expires_at",
        "email_verification_challenges",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_email_verification_challenges_active_user",
        "email_verification_challenges",
        ["user_id", "expires_at"],
        unique=False,
        postgresql_where=sa.text("consumed_at IS NULL AND revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_email_verification_challenges_active_user", table_name="email_verification_challenges")
    op.drop_index("ix_email_verification_challenges_expires_at", table_name="email_verification_challenges")
    op.drop_index("ix_email_verification_challenges_user_id", table_name="email_verification_challenges")
    op.drop_table("email_verification_challenges")
