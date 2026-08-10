"""Phase 4 versioned broker desired state and realtime membership generation.

Revision ID: 0019_phase4_p0_hardening
Revises: 0018_phase3_abuse_hardening
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0019_phase4_p0_hardening"
down_revision = "0018_phase3_abuse_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "channels",
        sa.Column("membership_generation", sa.BigInteger(), server_default="1", nullable=False),
    )
    op.create_table(
        "broker_binding_states",
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("generation", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("desired_bound", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("desired_routing_key", sa.String(length=255), nullable=False),
        sa.Column("routing_keys", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("reconciled_generation", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("channel_id", "user_id"),
    )
    op.create_index("ix_broker_binding_states_user", "broker_binding_states", ["user_id"], unique=False)
    op.create_index(
        "ix_broker_binding_states_pending",
        "broker_binding_states",
        ["generation", "reconciled_generation"],
        unique=False,
    )

    # Include both current memberships and every pair represented by a Phase-3
    # historical command. This preserves enough routing-key knowledge to remove
    # stale bindings for users whose membership was already deleted.
    op.execute(
        """
        WITH known_pairs AS (
            SELECT cm.channel_id, cm.user_id
            FROM channel_memberships AS cm
            UNION
            SELECT o.channel_id, o.aggregate_id AS user_id
            FROM outbox AS o
            JOIN users AS u ON u.id = o.aggregate_id
            WHERE o.aggregate_type = 'broker_binding'
        ),
        known_routing_keys AS (
            SELECT keys.channel_id,
                   keys.user_id,
                   jsonb_agg(DISTINCT keys.routing_key) AS routing_keys
            FROM (
                SELECT kp.channel_id,
                       kp.user_id,
                       'channel.' || c.channel_slug AS routing_key
                FROM known_pairs AS kp
                JOIN channels AS c ON c.id = kp.channel_id
                UNION ALL
                SELECT o.channel_id,
                       o.aggregate_id AS user_id,
                       'channel.' || (o.payload::jsonb ->> 'channel_slug') AS routing_key
                FROM outbox AS o
                JOIN users AS u ON u.id = o.aggregate_id
                WHERE o.aggregate_type = 'broker_binding'
                  AND (o.payload::jsonb ->> 'channel_slug') ~ '^[A-Za-z0-9_-]{3,50}$'
            ) AS keys
            GROUP BY keys.channel_id, keys.user_id
        )
        INSERT INTO broker_binding_states (
            channel_id,
            user_id,
            generation,
            desired_bound,
            desired_routing_key,
            routing_keys,
            reconciled_generation
        )
        SELECT kp.channel_id,
               kp.user_id,
               1,
               COALESCE((
                   c.deleted_at IS NULL
                   AND cm.role::text IN ('owner', 'admin', 'member')
               ), false),
               'channel.' || c.channel_slug,
               COALESCE(krk.routing_keys, jsonb_build_array('channel.' || c.channel_slug)),
               0
        FROM known_pairs AS kp
        JOIN channels AS c ON c.id = kp.channel_id
        JOIN users AS u ON u.id = kp.user_id
        LEFT JOIN channel_memberships AS cm
          ON cm.channel_id = kp.channel_id
         AND cm.user_id = kp.user_id
        LEFT JOIN known_routing_keys AS krk
          ON krk.channel_id = kp.channel_id
         AND krk.user_id = kp.user_id
        ON CONFLICT (channel_id, user_id) DO NOTHING
        """
    )

    # Legacy action rows are harmless under the new worker (they are recognized
    # as superseded), while these snapshots guarantee that every known pair has
    # a current generation available for retry/reconciliation after upgrade.
    op.execute(
        """
        INSERT INTO outbox (
            id,
            aggregate_type,
            aggregate_id,
            channel_id,
            payload,
            type,
            routing_key,
            status,
            attempts,
            max_attempts,
            created_at,
            updated_at
        )
        SELECT gen_random_uuid(),
               'broker_binding',
               bs.user_id,
               bs.channel_id,
               jsonb_build_object(
                   'type', 'broker_binding',
                   'schema_version', 1,
                   'generation', bs.generation,
                   'user_id', bs.user_id::text,
                   'channel_id', bs.channel_id::text
               )::json,
               'broker_binding.reconcile',
               'broker.binding',
               'pending',
               0,
               5,
               now(),
               now()
        FROM broker_binding_states AS bs
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM outbox
        WHERE aggregate_type = 'broker_binding'
          AND type = 'broker_binding.reconcile'
          AND payload::jsonb ->> 'schema_version' = '1'
        """
    )
    op.drop_index("ix_broker_binding_states_pending", table_name="broker_binding_states")
    op.drop_index("ix_broker_binding_states_user", table_name="broker_binding_states")
    op.drop_table("broker_binding_states")
    op.drop_column("channels", "membership_generation")
