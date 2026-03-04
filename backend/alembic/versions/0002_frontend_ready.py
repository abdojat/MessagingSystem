"""frontend ready additions

Revision ID: 0002_frontend_ready
Revises: 0001_phase3
Create Date: 2026-03-04
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0002_frontend_ready"
down_revision = "0001_phase3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("channels", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("user_sessions", sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("messages", sa.Column("client_msg_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_unique_constraint(
        "uq_messages_client_msg",
        "messages",
        ["channel_id", "sender_user_id", "client_msg_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_messages_client_msg", "messages", type_="unique")
    op.drop_column("messages", "client_msg_id")
    op.drop_column("user_sessions", "last_used_at")
    op.drop_column("channels", "deleted_at")
