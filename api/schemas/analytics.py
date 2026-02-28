from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TxType(str, Enum):
    CONTRIBUTION = "CONTRIBUTION"
    PAYOUT = "PAYOUT"
    ARREARS = "ARREARS"
    SETTLEMENT = "SETTLEMENT"
    LATE_CONTRIBUTION = "LATE_CONTRIBUTION"
    DELAYED_PAYOUT = "DELAYED_PAYOUT"
    LATE_FEE = "LATE_FEE"
    LATE_FEE_COMPENSATION = "LATE_FEE_COMPENSATION"
    REMOVAL_REFUND = "REMOVAL_REFUND"
    POT_HELD = "POT_HELD"


class MemberAnalyticsRow(BaseModel):
    entry_id: UUID
    circle_id: UUID
    member_id: UUID
    circle_month: int
    tx_type: TxType
    amount: Decimal
    status: str
    note: Optional[str] = None
    timestamp: datetime
    scheduled_recipient_id: Optional[UUID] = None

    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={Decimal: str},
    )
