"""invite token hashing and index parity

Revision ID: 0007_invite_hash_index
Revises: 0006_channel_last_seq_id
Create Date: 2026-03-05
"""

import hashlib

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0007_invite_hash_index"
down_revision = "0006_channel_last_seq_id"
branch_labels = None
depends_on = None


# Applies this schema revision; Alembic calls it while moving the database schema between revisions.
def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Run this conditional step only when `inspector.has_table('channel_invites')` is true.
    if inspector.has_table("channel_invites"):
        op.execute("ALTER TABLE channel_invites ADD COLUMN IF NOT EXISTS token_hash VARCHAR(128);")
        op.execute("ALTER TABLE channel_invites ADD COLUMN IF NOT EXISTS token_mask_prefix VARCHAR(8) NOT NULL DEFAULT '****';")
        op.execute("ALTER TABLE channel_invites ADD COLUMN IF NOT EXISTS token_mask_suffix VARCHAR(8) NOT NULL DEFAULT '****';")
        op.execute("ALTER TABLE channel_invites ALTER COLUMN token DROP NOT NULL;")

        rows = bind.execute(sa.text("SELECT id, token FROM channel_invites")).mappings().all()
        # Process each `row` from `rows` to apply this step to the full collection.
        for row in rows:
            raw_token = row["token"] or ""
            token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest() if raw_token else None
            prefix = raw_token[:4] if raw_token else "****"
            suffix = raw_token[-4:] if raw_token else "****"
            bind.execute(
                sa.text(
                    """
                    UPDATE channel_invites
                    SET token_hash = COALESCE(token_hash, :token_hash),
                        token_mask_prefix = COALESCE(token_mask_prefix, :prefix),
                        token_mask_suffix = COALESCE(token_mask_suffix, :suffix),
                        token = NULL
                    WHERE id = :id
                    """
                ),
                {"id": row["id"], "token_hash": token_hash, "prefix": prefix, "suffix": suffix},
            )

        op.execute("ALTER TABLE channel_invites ALTER COLUMN token_hash SET NOT NULL;")
        op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_channel_invites_token_hash ON channel_invites (token_hash);")
        op.execute("CREATE INDEX IF NOT EXISTS ix_channel_invites_channel_id ON channel_invites (channel_id);")
        op.execute("CREATE INDEX IF NOT EXISTS ix_channel_invites_expires_at ON channel_invites (expires_at);")

    # Run this conditional step only when `inspector.has_table('messages')` is true.
    if inspector.has_table("messages"):
        op.execute("ALTER TABLE messages DROP CONSTRAINT IF EXISTS uq_messages_client_msg;")
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_messages_client_msg_not_null ON messages (channel_id, sender_user_id, client_msg_id) WHERE client_msg_id IS NOT NULL;"
        )

    # Run this conditional step only when `inspector.has_table('uploads')` is true.
    if inspector.has_table("uploads"):
        op.execute("CREATE INDEX IF NOT EXISTS ix_uploads_created_at ON uploads (created_at);")


# Reverts this schema revision; Alembic calls it while moving the database schema between revisions.
def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_uploads_created_at;")
    op.execute("DROP INDEX IF EXISTS uq_messages_client_msg_not_null;")
    op.execute("ALTER TABLE messages ADD CONSTRAINT uq_messages_client_msg UNIQUE (channel_id, sender_user_id, client_msg_id);")
    op.execute("DROP INDEX IF EXISTS uq_channel_invites_token_hash;")
    op.execute("ALTER TABLE channel_invites DROP COLUMN IF EXISTS token_mask_suffix;")
    op.execute("ALTER TABLE channel_invites DROP COLUMN IF EXISTS token_mask_prefix;")
    op.execute("ALTER TABLE channel_invites DROP COLUMN IF EXISTS token_hash;")
