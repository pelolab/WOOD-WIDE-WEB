"""fix settlement dedup index to enforce idempotency key uniqueness

Revision ID: 0002
Revises: 0001
Create Date: 2026-02-24 11:00:00.000000
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_settlement_dedup;")
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_settlement_idempotency_key
        ON ledger (idempotency_key)
        WHERE idempotency_key IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_settlement_idempotency_key;")
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_settlement_dedup
        ON ledger (circle_id, debt_id, user_id, amount)
        WHERE type = 'SETTLEMENT';
        """
    )
