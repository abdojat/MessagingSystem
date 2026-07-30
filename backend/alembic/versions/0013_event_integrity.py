"""add event log integrity hash chain

Revision ID: 0013_event_integrity
Revises: 0012_delivery_reliability
Create Date: 2026-06-10
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0013_event_integrity"
down_revision = "0012_delivery_reliability"
branch_labels = None
depends_on = None


# Applies this schema revision; Alembic calls it while moving the database schema between revisions.
def upgrade() -> None:
    op.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS previous_hash varchar(64);")
    op.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS event_hash varchar(64);")
    op.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS hash_algorithm varchar(32);")
    op.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS integrity_version integer;")
    op.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS integrity_scope varchar(128);")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_events_integrity_scope_created ON events (integrity_scope, created_at, id);"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_events_event_hash ON events (event_hash);")


# Reverts this schema revision; Alembic calls it while moving the database schema between revisions.
def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_events_event_hash;")
    op.execute("DROP INDEX IF EXISTS ix_events_integrity_scope_created;")
    op.execute("ALTER TABLE events DROP COLUMN IF EXISTS integrity_scope;")
    op.execute("ALTER TABLE events DROP COLUMN IF EXISTS integrity_version;")
    op.execute("ALTER TABLE events DROP COLUMN IF EXISTS hash_algorithm;")
    op.execute("ALTER TABLE events DROP COLUMN IF EXISTS event_hash;")
    op.execute("ALTER TABLE events DROP COLUMN IF EXISTS previous_hash;")
