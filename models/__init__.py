from __future__ import annotations

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)


class Circle(Base):
    __tablename__ = "circles"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    contribution_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    loan_principal: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    loan_apr: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    loan_term_years: Mapped[float | None] = mapped_column(Numeric(4, 1), nullable=True)
    sovereignty_loan_principal: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    sovereignty_loan_apr: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    sovereignty_loan_term_years: Mapped[float | None] = mapped_column(Numeric(4, 1), nullable=True)

    members: Mapped[list["CircleMember"]] = relationship(back_populates="circle")


class CircleMember(Base):
    __tablename__ = "circle_members"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    circle_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("circles.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="member")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
    missed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    late_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    has_received_payout: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    debts_penalized_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    circle: Mapped[Circle] = relationship(back_populates="members")
    @property
    def display_name(self) -> str:
        return self.name




class LedgerEntry(Base):
    __tablename__ = "ledger"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    circle_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("circles.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    related_user_id: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    member: Mapped[str] = mapped_column(String(255), nullable=False)
    circle_month: Mapped[int] = mapped_column(Integer, nullable=False)
    tx_type: Mapped[str] = mapped_column("type", String(50), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    debt_id: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    intended_for: Mapped[str | None] = mapped_column(String(255), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True, default="")
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    timestamp: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserVerification(Base):
    __tablename__ = "user_verifications"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    tier: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="unverified")
    verified_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SocialVoucher(Base):
    __tablename__ = "social_vouchers"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    prospect_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    voucher_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)


# compatibility aliases
CircleModel = Circle
CircleMemberModel = CircleMember
LedgerEntryModel = LedgerEntry
Member = CircleMember
