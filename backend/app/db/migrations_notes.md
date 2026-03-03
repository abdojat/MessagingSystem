Migrations are managed with Alembic.

Commands:
- alembic upgrade head
- alembic downgrade -1

Initial migration creates enums and all phase-3 tables, including `channel_counters`.
