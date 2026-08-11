"""Phase 11 Merkle audit checkpoints and leaf snapshots.

Revision ID: 0024_phase11_merkle_audit
Revises: 0023_phase10_email_verification
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0024_phase11_merkle_audit"
down_revision = "0023_phase10_email_verification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_merkle_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence_no", sa.BigInteger(), nullable=False),
        sa.Column("merkle_version", sa.SmallInteger(), nullable=False),
        sa.Column("hash_algorithm", sa.String(length=32), nullable=False),
        sa.Column("leaf_count", sa.Integer(), nullable=False),
        sa.Column("first_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("last_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("first_event_hash", sa.String(length=64), nullable=False),
        sa.Column("last_event_hash", sa.String(length=64), nullable=False),
        sa.Column("merkle_root", sa.String(length=64), nullable=False),
        sa.Column("previous_checkpoint_hash", sa.String(length=64), nullable=True),
        sa.Column("checkpoint_hash", sa.String(length=64), nullable=False),
        sa.Column("signing_key_id", sa.String(length=64), nullable=False),
        sa.Column("signature", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("sequence_no >= 1", name="ck_audit_merkle_batches_sequence_positive"),
        sa.CheckConstraint("leaf_count BETWEEN 1 AND 4096", name="ck_audit_merkle_batches_leaf_count"),
        sa.CheckConstraint("merkle_version = 1", name="ck_audit_merkle_batches_version"),
        sa.CheckConstraint("hash_algorithm = 'sha256'", name="ck_audit_merkle_batches_algorithm"),
        sa.CheckConstraint("first_event_hash ~ '^[0-9a-f]{64}$'", name="ck_audit_merkle_batches_first_hash"),
        sa.CheckConstraint("last_event_hash ~ '^[0-9a-f]{64}$'", name="ck_audit_merkle_batches_last_hash"),
        sa.CheckConstraint("merkle_root ~ '^[0-9a-f]{64}$'", name="ck_audit_merkle_batches_root"),
        sa.CheckConstraint(
            "previous_checkpoint_hash IS NULL OR previous_checkpoint_hash ~ '^[0-9a-f]{64}$'",
            name="ck_audit_merkle_batches_previous_hash",
        ),
        sa.CheckConstraint("checkpoint_hash ~ '^[0-9a-f]{64}$'", name="ck_audit_merkle_batches_checkpoint_hash"),
        sa.CheckConstraint(
            "signing_key_id ~ '^[A-Za-z0-9_-]{1,64}$'",
            name="ck_audit_merkle_batches_signing_key",
        ),
        sa.ForeignKeyConstraint(["first_event_id"], ["events.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["last_event_id"], ["events.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("checkpoint_hash", name="uq_audit_merkle_batches_checkpoint_hash"),
        sa.UniqueConstraint("sequence_no", name="uq_audit_merkle_batches_sequence_no"),
    )
    op.create_index(
        "ix_audit_merkle_batches_created", "audit_merkle_batches", ["created_at"], unique=False
    )

    op.create_table(
        "audit_merkle_leaves",
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("leaf_index", sa.Integer(), nullable=False),
        sa.Column("event_hash", sa.String(length=64), nullable=False),
        sa.Column("leaf_hash", sa.String(length=64), nullable=False),
        sa.CheckConstraint("leaf_index >= 0", name="ck_audit_merkle_leaves_index"),
        sa.CheckConstraint("event_hash ~ '^[0-9a-f]{64}$'", name="ck_audit_merkle_leaves_event_hash"),
        sa.CheckConstraint("leaf_hash ~ '^[0-9a-f]{64}$'", name="ck_audit_merkle_leaves_leaf_hash"),
        sa.ForeignKeyConstraint(["batch_id"], ["audit_merkle_batches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("batch_id", "leaf_index"),
        sa.UniqueConstraint("event_id", name="uq_audit_merkle_leaves_event_id"),
    )
    op.create_index(
        "ix_audit_merkle_leaves_batch_index",
        "audit_merkle_leaves",
        ["batch_id", "leaf_index"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_audit_merkle_leaves_batch_index", table_name="audit_merkle_leaves")
    op.drop_table("audit_merkle_leaves")
    op.drop_index("ix_audit_merkle_batches_created", table_name="audit_merkle_batches")
    op.drop_table("audit_merkle_batches")
