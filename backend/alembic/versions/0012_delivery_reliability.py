"""add delivery reliability tracking

Revision ID: 0012_delivery_reliability
Revises: 0011_safe_routing_ids
Create Date: 2026-06-10
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0012_delivery_reliability"
down_revision = "0011_safe_routing_ids"
branch_labels = None
depends_on = None


# Applies this schema revision; Alembic calls it while moving the database schema between revisions.
def upgrade() -> None:
    # PostgreSQL enum values must be committed before they are used in UPDATEs.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE outbox_status ADD VALUE IF NOT EXISTS 'publishing';")
        op.execute("ALTER TYPE outbox_status ADD VALUE IF NOT EXISTS 'published';")
        op.execute("ALTER TYPE outbox_status ADD VALUE IF NOT EXISTS 'retry_scheduled';")
        op.execute("ALTER TYPE outbox_status ADD VALUE IF NOT EXISTS 'dead_lettered';")

    op.execute("ALTER TABLE outbox ADD COLUMN IF NOT EXISTS max_attempts integer NOT NULL DEFAULT 5;")
    op.execute("ALTER TABLE outbox ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();")
    op.execute("ALTER TABLE outbox ADD COLUMN IF NOT EXISTS dead_lettered_at timestamptz;")

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_enum e
                JOIN pg_type t ON t.oid = e.enumtypid
                WHERE t.typname = 'outbox_status'
                  AND e.enumlabel = 'sent'
            ) THEN
                EXECUTE '
                    UPDATE outbox
                    SET status = ''published'',
                        published_at = COALESCE(published_at, sent_at, now()),
                        updated_at = now(),
                        last_error = NULL,
                        next_retry_at = NULL
                    WHERE status = ''sent''
                ';
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        UPDATE outbox
        SET status = 'dead_lettered',
            dead_lettered_at = COALESCE(dead_lettered_at, now()),
            updated_at = now()
        WHERE status = 'failed'
          AND attempts >= max_attempts;
        """
    )
    op.execute(
        """
        UPDATE outbox
        SET status = 'retry_scheduled',
            next_retry_at = COALESCE(next_retry_at, now()),
            updated_at = now()
        WHERE status = 'failed'
          AND attempts < max_attempts;
        """
    )

    op.execute("CREATE INDEX IF NOT EXISTS ix_outbox_dead_lettered_at ON outbox (dead_lettered_at);")


# Reverts this schema revision; Alembic calls it while moving the database schema between revisions.
def downgrade() -> None:
    # Keep this downgrade data-safe. PostgreSQL cannot remove enum values
    # without recreating the type, and doing so would risk existing outbox rows.
    pass
