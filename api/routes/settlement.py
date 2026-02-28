from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from api.dependencies.auth import get_current_user_and_set_context
from core.security import verify_cash_transfer
from database.session import get_db
from models.ledger import LedgerEntry
from schemas.settlement import SettleArrearsRequest, SettlementResponse

router = APIRouter()


@router.post("/api/cycles/settle", response_model=SettlementResponse)
def execute_settlement(
    payload: SettleArrearsRequest,
    db: Session = Depends(get_db),
    _current_user_id: str = Depends(get_current_user_and_set_context),
):
    """
    Execute a directed settlement under one ACID transaction.

    Flow:
      1) Lock and load the target pending ARREARS entry.
      2) Recompute remaining debt from immutable SETTLEMENT rows.
      3) Validate cash sufficiency for principal + fee.
      4) Append immutable settlement-side ledger entries.
      5) Verify cash transfer and commit atomically.
    """

    target_debt = (
        db.query(LedgerEntry)
        .filter(
            LedgerEntry.id == payload.debt_id,
            LedgerEntry.status == "PENDING",
            LedgerEntry.tx_type == "ARREARS",
        )
        .with_for_update()
        .first()
    )

    if not target_debt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pending debt not found or already settled.",
        )

    already_paid = (
        db.query(func.sum(LedgerEntry.amount))
        .filter(
            LedgerEntry.debt_id == target_debt.id,
            LedgerEntry.tx_type == "SETTLEMENT",
        )
        .scalar()
        or 0.0
    )

    remaining = round(float(target_debt.amount) - float(already_paid), 2)
    if remaining <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Debt is already fully settled.",
        )

    principal_paid = round(min(float(payload.cash_received), remaining), 2)

    # If your product has grace rules and member late-strike tracking,
    # derive this dynamically from member/cycle state.
    fee = round(principal_paid * 0.05, 2)
    total_required = round(principal_paid + fee, 2)

    if float(payload.cash_received) < total_required:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Insufficient cash. "
                f"Required: ${total_required:.2f}, "
                f"Provided: ${float(payload.cash_received):.2f}"
            ),
        )

    try:
        settlement_entry = LedgerEntry(
            tx_type="SETTLEMENT",
            amount=principal_paid,
            debt_id=target_debt.id,
            member=payload.member_id,
            status="VERIFIED",
            note="settlement recorded via /api/cycles/settle",
        )

        late_contribution = LedgerEntry(
            tx_type="LATE_CONTRIBUTION",
            amount=principal_paid,
            member=payload.member_id,
            status="VERIFIED",
            note=f"late contribution for debt {target_debt.id}",
        )

        late_fee_entry = LedgerEntry(
            tx_type="LATE_FEE",
            amount=fee,
            member=payload.member_id,
            status="VERIFIED",
            note=f"late fee for debt {target_debt.id}",
        )

        delayed_payout = LedgerEntry(
            tx_type="DELAYED_PAYOUT",
            amount=-principal_paid,
            debt_id=target_debt.id,
            member=target_debt.intended_for,
            intended_for=target_debt.intended_for,
            status="VERIFIED",
            note=f"principal compensation from {payload.member_id}",
        )

        fee_compensation = LedgerEntry(
            tx_type="LATE_FEE_COMPENSATION",
            amount=-fee,
            member=target_debt.intended_for,
            intended_for=target_debt.intended_for,
            status="VERIFIED",
            note=f"fee compensation from {payload.member_id}",
        )

        db.add_all(
            [
                settlement_entry,
                late_contribution,
                late_fee_entry,
                delayed_payout,
                fee_compensation,
            ]
        )

        verify_cash_transfer(payload.member_id, total_required)
        db.commit()

    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Transaction failed due to database error. Ledger untouched.",
        )
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Transaction failed. Ledger untouched.",
        )

    return SettlementResponse(
        status="SUCCESS",
        principal_settled=principal_paid,
        fee_paid=fee,
    )
