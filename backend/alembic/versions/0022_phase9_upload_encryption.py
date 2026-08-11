"""Phase 9 upload encrypted-storage metadata.

Revision ID: 0022_phase9_upload_encryption
Revises: 0021_phase7_attachment_integrity
"""

import sqlalchemy as sa
from alembic import op


revision = "0022_phase9_upload_encryption"
down_revision = "0021_phase7_attachment_integrity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing rows intentionally begin at version 0. Their file bytes are
    # migrated separately by the bounded operator command, never by Alembic.
    op.add_column(
        "uploads",
        sa.Column("storage_encryption_version", sa.SmallInteger(), nullable=False, server_default="0"),
    )
    op.add_column("uploads", sa.Column("storage_key_id", sa.String(length=64), nullable=True))
    op.create_check_constraint(
        "ck_uploads_storage_encryption_metadata",
        "uploads",
        "(storage_encryption_version = 0 AND storage_key_id IS NULL) OR "
        "(storage_encryption_version = 1 AND storage_key_id IS NOT NULL)",
    )
    op.create_index(
        "ix_uploads_storage_encryption",
        "uploads",
        ["storage_encryption_version", "storage_key_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_uploads_storage_encryption", table_name="uploads")
    op.drop_constraint("ck_uploads_storage_encryption_metadata", "uploads", type_="check")
    op.drop_column("uploads", "storage_key_id")
    op.drop_column("uploads", "storage_encryption_version")
