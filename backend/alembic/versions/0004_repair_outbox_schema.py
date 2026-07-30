"""repair outbox schema drift

Revision ID: 0004_repair_outbox_schema
Revises: 0003_frontend_contract_parity
Create Date: 2026-03-04
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0004_repair_outbox_schema"
down_revision = "0003_frontend_contract_parity"
branch_labels = None
depends_on = None


# Applies this schema revision; Alembic calls it while moving the database schema between revisions.
def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Some existing databases are stamped at 0003 but contain only alembic_version.
    # Bootstrap all missing tables from ORM metadata in that case.
    if not inspector.has_table("channels"):
        from app.db.models import Base

        Base.metadata.create_all(bind=bind)
        return

    # Some existing databases are stamped at 0003 but are missing outbox.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'outbox_status') THEN
                CREATE TYPE outbox_status AS ENUM ('pending', 'sent', 'failed');
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS outbox (
            id uuid PRIMARY KEY,
            aggregate_type varchar(64) NOT NULL,
            aggregate_id uuid NOT NULL,
            channel_id uuid NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
            payload json NOT NULL,
            routing_key varchar(255) NOT NULL,
            status outbox_status NOT NULL DEFAULT 'pending',
            attempts integer NOT NULL DEFAULT 0,
            last_error text,
            created_at timestamptz NOT NULL DEFAULT now(),
            sent_at timestamptz,
            next_retry_at timestamptz
        );
        """
    )

    op.execute("ALTER TABLE outbox ADD COLUMN IF NOT EXISTS type varchar(128);")
    op.execute("ALTER TABLE outbox ADD COLUMN IF NOT EXISTS published_at timestamptz;")
    op.execute("CREATE INDEX IF NOT EXISTS ix_outbox_status_next_retry ON outbox (status, next_retry_at);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_outbox_published_at ON outbox (published_at);")


# Reverts this schema revision; Alembic calls it while moving the database schema between revisions.
def downgrade() -> None:
    # Intentionally no-op: this migration repairs drift and should not remove data.
    pass
