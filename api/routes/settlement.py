from __future__ import annotations

import logging
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_async_db, get_current_user_id
from api.schemas.settlement import SettleArrearsRequest, SettlementResponse
from core.circle_service import get_circle_engine, persist_engine
from models import LedgerEntry as LedgerEntryModel
from models import Member as MemberModel
from app.rate_limiter import limiter

log = logging.getLogger("susucircle.api")
router = APIRouter()


async def _authorize_and_resolve_member(
    db: AsyncSession,
    circle_id: UUID,
    current_user_id: str,
    target_member_id: UUID,
) -> tuple[str, UUID]:
    caller_result = await db.execute(
        select(MemberModel.role).where(
            MemberModel.circle_id == circle_id,
            MemberModel.user_id == UUID(current_user_id),
        )
    )
    caller_role = caller_result.scalar_one_or_none()

    if caller_role is None:
        raise HTTPException(403, "Not a member of this circle")
    if caller_role != "admin" and str(target_member_id) != current_user_id:
        raise HTTPException(403, "You can only settle your own debts")

    target_result = await db.execute(
        select(MemberModel.name, MemberModel.user_id).where(
            MemberModel.circle_id == circle_id,
            MemberModel.user_id == target_member_id,
            MemberModel.status != "removed",
        )
    )
    target_row = target_result.one_or_none()

    if target_row is None:
        raise HTTPException(404, "Member not found or removed")

    return target_row.name, target_row.user_id


async def _build_cached_response(db: AsyncSession, circle_id: UUID, idempotency_key: str) -> SettlementResponse:
    row = (
        await db.execute(
            select(LedgerEntryModel)
            .where(
                LedgerEntryModel.circle_id == circle_id,
                LedgerEntryModel.idempotency_key == idempotency_key,
                LedgerEntryModel.tx_type == "SETTLEMENT",
            )
            .order_by(LedgerEntryModel.created_at.desc())
        )
    ).scalar_one()

    amount = Decimal(str(row.amount or "0.00"))
    debt_id = row.debt_id or UUID(int=0)

    return SettlementResponse(
        debtor=row.member,
        creditor="",
        debt_id=UUID(str(debt_id)),
        from_month=row.circle_month,
        settled_in_month=row.circle_month,
        principal_paid=amount,
        remaining_principal=Decimal("0.00"),
        late_fee_applied=Decimal("0.00"),
        total_cash=amount,
        fully_settled=False,
    )


@router.post("/cycles/{circle_id}/settle", response_model=SettlementResponse)
@limiter.limit("10/minute")
async def execute_settlement(
    request: Request,
    circle_id: UUID,
    payload: SettleArrearsRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user_id: str = Depends(get_current_user_id),
):
    if payload.idempotency_key:
        existing = await db.execute(
            select(LedgerEntryModel)
            .where(
                LedgerEntryModel.circle_id == circle_id,
                LedgerEntryModel.idempotency_key == payload.idempotency_key,
                LedgerEntryModel.tx_type == "SETTLEMENT",
            )
            .with_for_update()
        )
        if existing.scalar_one_or_none():
            return await _build_cached_response(db, circle_id, payload.idempotency_key)

    try:
        engine = await get_circle_engine(db, circle_id, for_update=True)
    except RuntimeError as e:
        log.error(f"Engine init failed for circle {circle_id}: {e}")
        if "not found" in str(e).lower():
            raise HTTPException(404, "Circle not found")
        raise HTTPException(500, "Internal server error") from e

    member_name, verified_member_uid = await _authorize_and_resolve_member(
        db, circle_id, current_user_id, payload.member_id,
    )

    engine_member_uid_map = {
        member.name: member.user_id
        for member in getattr(engine, "_db_member_records", {}).values()
        if getattr(member, "user_id", None) is not None
    }
    engine_member_uid_map[member_name] = verified_member_uid

    ledger_snapshot = len(engine.ledger)

    try:
        result = engine.settle_arrears(
            member=member_name,
            amount_paid=payload.amount_paid,
            debt_id=str(payload.debt_id) if payload.debt_id else None,
        )
    except ValueError as e:
        raise HTTPException(422, detail=str(e))
    except RuntimeError as e:
        log.error(f"Engine integrity error in circle {circle_id}: {e}")
        raise HTTPException(500, "Internal engine error") from e

    if result is None:
        raise HTTPException(404, "No pending arrears found for this member")

    try:
        await persist_engine(
            db,
            circle_id,
            engine,
            new_entries_from=ledger_snapshot,
            idempotency_key=payload.idempotency_key,
            member_user_id_map=engine_member_uid_map,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        log.exception(f"Persist failed for settlement in circle {circle_id}")
        raise HTTPException(500, "Settlement computed but failed to save. Please retry.")

    return SettlementResponse(
        debtor=result["debtor"],
        creditor=result["creditor"],
        debt_id=UUID(result["debt_id"]),
        from_month=result["from_month"],
        settled_in_month=result["settled_in_month"],
        principal_paid=result["principal_paid"],
        remaining_principal=result["remaining"],
        late_fee_applied=result["late_fee"],
        total_cash=result["total_cash"],
        fully_settled=result["fully_settled"],
    )
