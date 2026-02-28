"""baseline schema with RLS and constraints

Revision ID: 0001
Revises:
Create Date: 2026-02-24 10:00:00.000000

This is the Alembic baseline for all existing environments.
For databases that already have the schema, run: alembic stamp 0001
For fresh databases, run: alembic upgrade head
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers, used by Alembic.
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 0. Auth Schema + Helper Functions ──────────────────────────
    op.execute("CREATE SCHEMA IF NOT EXISTS auth;")
    op.execute("""
        CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid
        LANGUAGE sql STABLE AS $$
            SELECT NULLIF(current_setting('auth.uid', true), '')::uuid;
        $$;
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION auth.role() RETURNS text
        LANGUAGE sql STABLE AS $$
            SELECT NULLIF(current_setting('auth.role', true), '');
        $$;
    """)

    # ── 1. Users ───────────────────────────────────────────────────
    # Referenced by: identity.py (User.id, User.full_name)
    #               auth.py (set_config auth.uid)
    #               RLS policies (users.id = auth.uid())
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), unique=True, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    # ── 2. Circles ─────────────────────────────────────────────────
    # Referenced by: circle_service.py (CircleModel.id, .members relationship)
    #               analytics.py (CircleModel with loan term fields)
    #               settlement.py (FOR UPDATE lock target)
    op.create_table(
        "circles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("contribution_amount", sa.Numeric(12, 2), nullable=False, server_default="100.00"),
        sa.Column("loan_principal", sa.Numeric(12, 2), nullable=True),
        sa.Column("loan_apr", sa.Numeric(5, 4), nullable=True),
        sa.Column("loan_term_years", sa.Numeric(4, 1), nullable=True),
        sa.Column("sovereignty_loan_principal", sa.Numeric(12, 2), nullable=True),
        sa.Column("sovereignty_loan_apr", sa.Numeric(5, 4), nullable=True),
        sa.Column("sovereignty_loan_term_years", sa.Numeric(4, 1), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    # ── 3. Circle Members ──────────────────────────────────────────
    # Referenced by: circle_service.py (name, status, missed_count, late_count,
    #               has_received_payout, debts_penalized_json, user_id)
    #               settlement.py (MemberModel.role, .name, .user_id, .status)
    #               identity.py (CircleMember.user_id, .status)
    #               RLS policies (circle_members.user_id = auth.uid())
    op.create_table(
        "circle_members",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("circle_id", UUID(as_uuid=True), sa.ForeignKey("circles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("role", sa.String(50), nullable=False, server_default="member"),
        sa.Column("status", sa.String(50), nullable=False, server_default="active"),
        sa.Column("missed_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("late_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("has_received_payout", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("debts_penalized_json", JSONB, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.UniqueConstraint("circle_id", "user_id", name="uq_circle_member"),
    )

    # ── 4. Ledger ──────────────────────────────────────────────────
    # Referenced by: analytics.py raw SQL (id, circle_id, user_id, circle_month,
    #               type/tx_type, amount, status, note, timestamp, intended_for)
    #               circle_service.py (circle_month, tx_type, member, amount,
    #               status, debt_id, intended_for, note, created_at)
    #               settlement.py (idempotency_key, tx_type, circle_id)
    #               RLS policies (user_id, related_user_id, circle_id)
    #
    # NOTE: The analytics raw SQL uses "type" as the column name aliased to tx_type.
    #       The ORM uses "tx_type". We use "type" as the DB column to match the raw SQL,
    #       and the ORM model should map it: tx_type = Column("type", String).
    op.create_table(
        "ledger",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("circle_id", UUID(as_uuid=True), sa.ForeignKey("circles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("related_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("member", sa.String(255), nullable=False),
        sa.Column("circle_month", sa.Integer, nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("debt_id", UUID(as_uuid=True), nullable=True),
        sa.Column("intended_for", sa.String(255), nullable=True),
        sa.Column("note", sa.Text, nullable=True, server_default=""),
        sa.Column("idempotency_key", sa.String(255), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    # ── 5. User Verifications ──────────────────────────────────────
    # Referenced by: identity.py (user_id, tier, status, verified_at)
    op.create_table(
        "user_verifications",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tier", sa.Integer, nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="unverified"),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.UniqueConstraint("user_id", "tier", name="uq_user_verification_tier"),
    )

    # ── 6. Social Vouchers ─────────────────────────────────────────
    # Referenced by: identity.py (prospect_id, voucher_id, id)
    #               RLS policies (prospect_id, voucher_id)
    op.create_table(
        "social_vouchers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("prospect_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("voucher_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.UniqueConstraint("prospect_id", "voucher_id", name="uq_vouch_pair"),
    )

    # ── 7. Enable Row Level Security ───────────────────────────────
    for table in ["users", "circles", "circle_members", "ledger", "social_vouchers"]:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")

    # ── 8. Canonical RLS Policies ──────────────────────────────────

    # Users: can only see own profile
    op.execute("""
        CREATE POLICY user_privacy_policy ON users
        FOR SELECT USING (id = auth.uid());
    """)

    # Circles: only members can see circle details
    op.execute("""
        CREATE POLICY circle_access_policy ON circles
        FOR SELECT USING (
            EXISTS (
                SELECT 1 FROM circle_members
                WHERE circle_id = circles.id AND user_id = auth.uid()
            )
        );
    """)

    # Ledger: read policy — own entries, related entries, or active circle member
    op.execute("""
        CREATE POLICY ledger_read_policy ON ledger
        FOR SELECT USING (
            user_id = auth.uid()
            OR related_user_id = auth.uid()
            OR EXISTS (
                SELECT 1 FROM circle_members
                WHERE circle_id = ledger.circle_id
                AND user_id = auth.uid()
                AND status = 'ACTIVE'
            )
        );
    """)

    # Ledger: write protection — service role only
    op.execute("""
        CREATE POLICY ledger_write_protection ON ledger
        FOR INSERT WITH CHECK (auth.role() = 'service_role');
    """)

    # Social vouchers: visibility
    op.execute("""
        CREATE POLICY social_vouchers_view ON social_vouchers
        FOR SELECT USING (auth.uid() = prospect_id OR auth.uid() = voucher_id);
    """)

    # Social vouchers: insert — only the voucher can create
    op.execute("""
        CREATE POLICY social_vouchers_insert ON social_vouchers
        FOR INSERT WITH CHECK (auth.uid() = voucher_id);
    """)

    # ── 9. Settlement Dedup Constraint (Blocker #8) ────────────────
    # Partial unique index — prevents exact duplicate SETTLEMENT writes.
    # Depends on user_id being populated (enforced by persist_engine assertion).
    op.execute("""
        CREATE UNIQUE INDEX uq_settlement_dedup
        ON ledger (circle_id, debt_id, user_id, amount)
        WHERE type = 'SETTLEMENT';
    """)

    # ── 10. Performance Indexes ────────────────────────────────────
    op.execute("""
        CREATE INDEX idx_ledger_analytics_lookup
        ON ledger (circle_id, circle_month DESC, timestamp DESC);
    """)

    op.execute("""
        CREATE INDEX idx_ledger_circle_created
        ON ledger (circle_id, created_at);
    """)

    op.execute("""
        CREATE INDEX idx_circle_members_user
        ON circle_members (user_id, status);
    """)


def downgrade() -> None:
    # ── Indexes ────────────────────────────────────────────────────
    op.execute("DROP INDEX IF EXISTS idx_circle_members_user;")
    op.execute("DROP INDEX IF EXISTS idx_ledger_circle_created;")
    op.execute("DROP INDEX IF EXISTS idx_ledger_analytics_lookup;")
    op.execute("DROP INDEX IF EXISTS uq_settlement_dedup;")

    # ── RLS Policies ───────────────────────────────────────────────
    op.execute("DROP POLICY IF EXISTS social_vouchers_insert ON social_vouchers;")
    op.execute("DROP POLICY IF EXISTS social_vouchers_view ON social_vouchers;")
    op.execute("DROP POLICY IF EXISTS ledger_write_protection ON ledger;")
    op.execute("DROP POLICY IF EXISTS ledger_read_policy ON ledger;")
    op.execute("DROP POLICY IF EXISTS circle_access_policy ON circles;")
    op.execute("DROP POLICY IF EXISTS user_privacy_policy ON users;")

    # ── Tables (reverse dependency order) ──────────────────────────
    op.drop_table("social_vouchers")
    op.drop_table("user_verifications")
    op.drop_table("ledger")
    op.drop_table("circle_members")
    op.drop_table("circles")
    op.drop_table("users")

    # ── Auth Schema ────────────────────────────────────────────────
    op.execute("DROP FUNCTION IF EXISTS auth.role();")
    op.execute("DROP FUNCTION IF EXISTS auth.uid();")
    op.execute("DROP SCHEMA IF EXISTS auth;")
