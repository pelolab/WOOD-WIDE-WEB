from __future__ import annotations

from decimal import Decimal
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_async_db, get_current_user_id
from api.schemas.analytics import MemberAnalyticsRow
from models import Circle

router = APIRouter(prefix="/api/circles", tags=["Analytics"])


async def _load_circle_loan_terms(db: AsyncSession, circle_id: UUID) -> tuple[Decimal, Decimal, Decimal]:
    circle = (await db.execute(select(Circle).where(Circle.id == circle_id))).scalar_one_or_none()

    if circle is None:
        return Decimal("3000.00"), Decimal("0.18"), Decimal("1.0")

    def pick(obj: object, names: list[str], default: Decimal) -> Decimal:
        for name in names:
            value = getattr(obj, name, None)
            if value is not None:
                return Decimal(str(value))
        return default

    principal = pick(circle, ["loan_principal", "sovereignty_loan_principal"], Decimal("3000.00"))
    apr = pick(circle, ["loan_apr", "sovereignty_loan_apr"], Decimal("0.18"))
    years = pick(circle, ["loan_term_years", "sovereignty_loan_term_years"], Decimal("1.0"))
    return principal, apr, years


@router.get("/{circleId}/analytics/members", response_model=List[MemberAnalyticsRow])
async def get_member_analytics(
    circleId: UUID,
    member_id: UUID | None = None,
    db: AsyncSession = Depends(get_async_db),
    _current_user_id: str = Depends(get_current_user_id),
):
    query = text(
        """
        SELECT
            id AS entry_id,
            circle_id,
            user_id AS member_id,
            circle_month,
            type AS tx_type,
            amount,
            status,
            note,
            timestamp,
            intended_for AS scheduled_recipient_id
        FROM ledger
        WHERE circle_id = :circle_id
          AND (:member_id IS NULL OR user_id = :member_id)
        ORDER BY circle_month DESC, timestamp DESC;
        """
    )
    rows = (await db.execute(query, {"circle_id": circleId, "member_id": member_id})).mappings().all()
    return [MemberAnalyticsRow.model_validate(r) for r in rows]


@router.get("/{circleId}/analytics/sovereignty")
async def get_sovereignty_projection(
    circleId: UUID,
    member_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    _current_user_id: str = Depends(get_current_user_id),
):
    query = text(
        """
        SELECT COALESCE(SUM(ABS(amount)), 0) AS liquidity
        FROM ledger
        WHERE circle_id = :circle_id
          AND user_id = :member_id
          AND type IN ('PAYOUT', 'DELAYED_PAYOUT')
        """
    )
    liquidity = Decimal((await db.execute(query, {"circle_id": circleId, "member_id": member_id})).scalar() or 0)
    principal, apr, years = await _load_circle_loan_terms(db, circleId)
    interest = (principal * apr * years).quantize(Decimal("0.01"))
    total = (principal + interest).quantize(Decimal("0.01"))
    return {
        "group_liquidity": str(liquidity.quantize(Decimal("0.01"))),
        "equivalent_loan_principal": str(principal.quantize(Decimal("0.01"))),
        "equivalent_loan_interest": str(interest),
        "total_loan_repayment": str(total),
        "savings_vs_loan": str((total - liquidity).quantize(Decimal("0.01"))),
    }
