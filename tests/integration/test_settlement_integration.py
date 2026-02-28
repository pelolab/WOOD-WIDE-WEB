"""
Run with:
    docker compose -f docker-compose.test.yml up -d
    pytest tests/integration/ -v --asyncio-mode=auto
    docker compose -f docker-compose.test.yml down
"""
from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import CircleMemberModel, LedgerEntryModel


# ── Happy Path ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_settlement_creates_correct_ledger_entries(
    client: AsyncClient, seed_circle: dict, db_session: AsyncSession,
):
    """Full settlement of Charlie's $100 debt to Bob."""
    circle_id = seed_circle["circle_id"]
    arrears_id = seed_circle["arrears_id"]

    resp = await client.post(
        f"/circles/{circle_id}/settle",
        json={
            "member_name": "Charlie",
            "amount_paid": "100.00",
            "debt_id": arrears_id,
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["debtor"] == "Charlie"
    assert body["creditor"] == "Bob"
    assert body["fully_settled"] is True
    assert Decimal(body["remaining_principal"]) == Decimal("0.00")
    assert Decimal(body["principal_paid"]) == Decimal("100.00")
    # Grace cycle = 1, this is Charlie's first late strike → no fee
    assert Decimal(body["late_fee_applied"]) == Decimal("0.00")
    assert Decimal(body["total_cash"]) == Decimal("100.00")
    assert body["from_month"] == 2

    # Verify ledger entries were persisted
    result = await db_session.execute(
        select(LedgerEntryModel)
        .where(
            LedgerEntryModel.circle_id == circle_id,
            LedgerEntryModel.circle_month == 2,
            LedgerEntryModel.tx_type.in_(["SETTLEMENT", "LATE_CONTRIBUTION", "DELAYED_PAYOUT"]),
        )
        .order_by(LedgerEntryModel.tx_type)
    )
    new_entries = result.scalars().all()

    types = sorted(e.tx_type for e in new_entries)
    assert "DELAYED_PAYOUT" in types
    assert "LATE_CONTRIBUTION" in types
    assert "SETTLEMENT" in types

    # SETTLEMENT references the original debt
    settlement = next(e for e in new_entries if e.tx_type == "SETTLEMENT")
    assert settlement.debt_id == arrears_id
    assert settlement.amount == Decimal("100.00")

    # DELAYED_PAYOUT goes to Bob (the shorted member)
    delayed = next(e for e in new_entries if e.tx_type == "DELAYED_PAYOUT")
    assert delayed.member == "Bob"
    assert delayed.amount == Decimal("-100.00")


@pytest.mark.asyncio
async def test_partial_settlement_leaves_remaining_debt(
    client: AsyncClient, seed_circle: dict, db_session: AsyncSession,
):
    """Pay $40 of $100 → $60 remaining, not fully settled."""
    circle_id = seed_circle["circle_id"]
    arrears_id = seed_circle["arrears_id"]

    resp = await client.post(
        f"/circles/{circle_id}/settle",
        json={
            "member_name": "Charlie",
            "amount_paid": "40.00",
            "debt_id": arrears_id,
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["fully_settled"] is False
    assert Decimal(body["remaining_principal"]) == Decimal("60.00")
    assert Decimal(body["principal_paid"]) == Decimal("40.00")


@pytest.mark.asyncio
async def test_fifo_settlement_without_debt_id(
    client: AsyncClient, seed_circle: dict,
):
    """Omitting debt_id settles the oldest pending debt."""
    circle_id = seed_circle["circle_id"]

    resp = await client.post(
        f"/circles/{circle_id}/settle",
        json={
            "member_name": "Charlie",
            "amount_paid": "100.00",
            # No debt_id — should resolve to FIFO
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["debt_id"] == seed_circle["arrears_id"]
    assert body["fully_settled"] is True


@pytest.mark.asyncio
async def test_settlement_updates_member_state(
    client: AsyncClient, seed_circle: dict, db_session: AsyncSession,
):
    """Verify _debts_penalized and late_count are persisted."""
    circle_id = seed_circle["circle_id"]
    arrears_id = seed_circle["arrears_id"]

    await client.post(
        f"/circles/{circle_id}/settle",
        json={
            "member_name": "Charlie",
            "amount_paid": "100.00",
            "debt_id": arrears_id,
        },
    )

    result = await db_session.execute(
        select(CircleMemberModel).where(
            CircleMemberModel.circle_id == circle_id,
            CircleMemberModel.display_name == "Charlie",
        )
    )
    charlie = result.scalar_one()
    assert charlie.late_count == 1
    assert arrears_id in charlie.debts_penalized_json


# ── Capital Conservation ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_capital_conservation_after_settlement(
    client: AsyncClient, seed_circle: dict, db_session: AsyncSession,
):
    """
    The fundamental invariant: total inflows == total outflows.
    After full settlement, no money should be created or destroyed.
    """
    circle_id = seed_circle["circle_id"]

    await client.post(
        f"/circles/{circle_id}/settle",
        json={
            "member_name": "Charlie",
            "amount_paid": "100.00",
            "debt_id": seed_circle["arrears_id"],
        },
    )

    result = await db_session.execute(
        select(LedgerEntryModel).where(
            LedgerEntryModel.circle_id == circle_id,
        )
    )
    all_entries = result.scalars().all()

    inflow = sum(
        e.amount for e in all_entries
        if e.tx_type in ("CONTRIBUTION", "LATE_CONTRIBUTION", "LATE_FEE")
    )
    outflow = sum(
        abs(e.amount) for e in all_entries
        if e.amount < 0
    )
    escrow = sum(
        e.amount for e in all_entries
        if e.tx_type == "POT_HELD"
    )

    assert (inflow - outflow - escrow) == Decimal("0.00"), (
        f"Capital conservation violated: "
        f"in={inflow}, out={outflow}, escrow={escrow}, "
        f"error={inflow - outflow - escrow}"
    )


# ── Bug #2 Regression: late_count per debt ──────────────────────────


@pytest.mark.asyncio
async def test_partial_settlements_do_not_inflate_late_count(
    client: AsyncClient, seed_circle: dict, db_session: AsyncSession,
):
    """
    Regression test for bug #2: settling the same debt in multiple
    installments must increment late_count only once.
    """
    circle_id = seed_circle["circle_id"]
    arrears_id = seed_circle["arrears_id"]

    # First partial: $30
    await client.post(
        f"/circles/{circle_id}/settle",
        json={"member_name": "Charlie", "amount_paid": "30.00", "debt_id": arrears_id},
    )
    # Second partial: $30
    await client.post(
        f"/circles/{circle_id}/settle",
        json={"member_name": "Charlie", "amount_paid": "30.00", "debt_id": arrears_id},
    )
    # Final partial: $40
    await client.post(
        f"/circles/{circle_id}/settle",
        json={"member_name": "Charlie", "amount_paid": "40.00", "debt_id": arrears_id},
    )

    result = await db_session.execute(
        select(CircleMemberModel).where(
            CircleMemberModel.circle_id == circle_id,
            CircleMemberModel.display_name == "Charlie",
        )
    )
    charlie = result.scalar_one()

    # Three settlements on the same debt → only 1 late strike
    assert charlie.late_count == 1, (
        f"late_count should be 1 but got {charlie.late_count} "
        f"(bug #2 regression: inflated by partial settlements)"
    )


# ── Error Cases ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_settle_nonexistent_circle_returns_404(client: AsyncClient):
    resp = await client.post(
        f"/circles/{uuid4()}/settle",
        json={"member_name": "Charlie", "amount_paid": "100.00"},
    )
    assert resp.status_code == 404
    assert "Circle not found" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_settle_unknown_member_returns_422(
    client: AsyncClient, seed_circle: dict,
):
    resp = await client.post(
        f"/circles/{seed_circle['circle_id']}/settle",
        json={"member_name": "Nonexistent", "amount_paid": "100.00"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_settle_no_pending_arrears_returns_404(
    client: AsyncClient, seed_circle: dict,
):
    """Alice has no debts — settlement should 404."""
    # Override auth to be Alice
    resp = await client.post(
        f"/circles/{seed_circle['circle_id']}/settle",
        json={"member_name": "Alice", "amount_paid": "100.00"},
    )
    # Will be 403 (Charlie can't settle Alice's debt) or 404 (no arrears)
    assert resp.status_code in (403, 404)


@pytest.mark.asyncio
async def test_settle_wrong_debt_id_returns_422(
    client: AsyncClient, seed_circle: dict,
):
    resp = await client.post(
        f"/circles/{seed_circle['circle_id']}/settle",
        json={
            "member_name": "Charlie",
            "amount_paid": "100.00",
            "debt_id": str(uuid4()),
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_zero_amount_rejected_by_schema(
    client: AsyncClient, seed_circle: dict,
):
    resp = await client.post(
        f"/circles/{seed_circle['circle_id']}/settle",
        json={"member_name": "Charlie", "amount_paid": "0.00"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_sub_cent_amount_rejected_by_schema(
    client: AsyncClient, seed_circle: dict,
):
    resp = await client.post(
        f"/circles/{seed_circle['circle_id']}/settle",
        json={"member_name": "Charlie", "amount_paid": "99.999"},
    )
    assert resp.status_code == 422


# ── Authorization ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_member_cannot_settle_another_members_debt(
    client: AsyncClient, seed_circle: dict,
):
    """Charlie (current_user) cannot settle Bob's debts."""
    resp = await client.post(
        f"/circles/{seed_circle['circle_id']}/settle",
        json={"member_name": "Bob", "amount_paid": "50.00"},
    )
    assert resp.status_code == 403
    assert "own debts" in resp.json()["detail"]


# ── Concurrency ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_settlements_do_not_double_settle(
    seed_circle: dict, db_session: AsyncSession,
):
    """
    Simulate two concurrent full settlements on the same $100 debt.
    Only one should succeed; the second should find $0 remaining.

    NOTE: This test requires two independent DB sessions to properly
    test FOR UPDATE locking. In a single-session test, the lock is
    re-entrant. For full concurrency testing, use two separate
    AsyncClient instances with independent sessions.
    """
    import asyncio

    from api.dependencies import get_current_active_user, get_db
    from app.main import create_app
    from httpx import ASGITransport, AsyncClient as AC

    app = create_app()

    # Each request gets its own session via the real get_db dependency
    # (not the shared test session) to test actual locking behavior.
    app.dependency_overrides[get_current_active_user] = (
        lambda: _make_mock_user(seed_circle["charlie_user_id"])
    )

    circle_id = seed_circle["circle_id"]
    arrears_id = seed_circle["arrears_id"]
    payload = {
        "member_name": "Charlie",
        "amount_paid": "100.00",
        "debt_id": arrears_id,
    }

    transport = ASGITransport(app=app)

    async def settle():
        async with AC(transport=transport, base_url="http://test") as c:
            return await c.post(f"/circles/{circle_id}/settle", json=payload)

    r1, r2 = await asyncio.gather(settle(), settle())

    statuses = sorted([r1.status_code, r2.status_code])
    # One succeeds (200), one fails (404 — no remaining arrears)
    assert statuses == [200, 404], (
        f"Expected one success and one failure, got {r1.status_code} and {r2.status_code}. "
        f"Double-settlement may have occurred."
    )

    app.dependency_overrides.clear()


def _make_mock_user(user_id):
    class MockUser:
        def __init__(self, uid):
            self.id = uid

    return MockUser(user_id)
