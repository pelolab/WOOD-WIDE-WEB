from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class SettleArrearsRequest(BaseModel):
    member_id: UUID
    amount_paid: Decimal = Field(gt=0)
    debt_id: UUID | None = None
    idempotency_key: str | None = None

    @field_validator("amount_paid")
    @classmethod
    def validate_two_dp(cls, value: Decimal) -> Decimal:
        if value.as_tuple().exponent < -2:
            raise ValueError("amount_paid must have max 2 decimal places")
        return value


class SettlementResponse(BaseModel):
    debtor: str
    creditor: str
    principal_paid: Decimal
    remaining_principal: Decimal
    late_fee_applied: Decimal
    total_cash: Decimal
    debt_id: UUID
    fully_settled: bool
    from_month: int
    settled_in_month: int
