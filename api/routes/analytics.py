from __future__ import annotations

import logging
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from api.dependencies.auth import get_current_user_and_set_context
from api.schemas.analytics import MemberAnalyticsRow
from database.session import get_db

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/circles", tags=["Analytics"])


@router.get("/{circleId}/analytics/members", response_model=List[MemberAnalyticsRow])
def get_member_analytics(
    circleId: UUID,
    db: Session = Depends(get_db),
    # This dependency sets auth.uid/auth.role in the Postgres session for RLS.
    _current_user_id: str = Depends(get_current_user_and_set_context),
):
    """
    Return a flattened ledger view for a specific circle.

    Access is enforced by database RLS policies.
    """

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
        ORDER BY circle_month DESC, timestamp DESC;
        """
    )

    try:
        rows = db.execute(query, {"circle_id": circleId}).mappings().all()
        return [MemberAnalyticsRow.model_validate(row) for row in rows]
    except SQLAlchemyError:
        log.exception("Database error fetching analytics for circle %s", circleId)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal Server Error",
        )
    except Exception:
        log.exception("Unexpected error fetching analytics for circle %s", circleId)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal Server Error",
        )
