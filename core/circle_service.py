from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select

from api.dependencies import set_service_role_context
from models import CircleModel, LedgerEntryModel
from susu_circle_engine_v3 import MemberRecord, MemberStatus, PaymentStatus, SusuCircle


async def get_circle_engine(db: Any, circle_id: UUID | str, for_update: bool = False) -> SusuCircle:
    stmt = select(CircleModel).where(CircleModel.id == circle_id)
    if for_update:
        stmt = stmt.with_for_update()

    circle = (await db.execute(stmt)).scalar_one_or_none()
    if circle is None:
        raise RuntimeError("Circle not found")

    member_names = [m.name for m in circle.members]
    engine = SusuCircle(member_names)

    member_records = {m.name: m for m in circle.members}

    for name in member_names:
        db_member = member_records.get(name)
        if db_member:
            engine.members[name] = MemberRecord(
                name=name,
                status=MemberStatus(db_member.status.upper()),
                missed_count=db_member.missed_count,
                late_count=db_member.late_count,
                has_received_payout=db_member.has_received_payout,
                _debts_penalized=set(db_member.debts_penalized_json or []),
            )
        else:
            engine.members[name] = MemberRecord(name=name)

    rows = (
        await db.execute(
            select(LedgerEntryModel)
            .where(LedgerEntryModel.circle_id == circle_id)
            .order_by(LedgerEntryModel.created_at)
        )
    ).scalars().all()

    for row in rows:
        engine._append(
            circle_month=row.circle_month,
            tx_type=row.tx_type,
            member=row.member,
            amount=row.amount,
            status=PaymentStatus(row.status),
            debt_id=row.debt_id,
            intended_for=row.intended_for,
            note=row.note or "",
        )

    engine._persisted_ledger_count = len(engine.ledger)  # type: ignore[attr-defined]
    engine._db_member_records = member_records  # type: ignore[attr-defined]
    return engine


async def persist_engine(
    db: Any,
    circle_id: UUID | str,
    engine: SusuCircle,
    new_entries_from: int = 0,
    idempotency_key: str | None = None,
    member_user_id_map: dict[str, UUID] | None = None,
) -> None:
    await set_service_role_context(db)

    if member_user_id_map is None:
        db_members = getattr(engine, "_db_member_records", {})
        member_user_id_map = {
            name: getattr(member, "user_id", None)
            for name, member in db_members.items()
        }

    new_entries = engine.ledger[new_entries_from:]
    for idx, entry in enumerate(new_entries):
        resolved_user_id = member_user_id_map.get(entry.member)
        if entry.tx_type.value == "SETTLEMENT" and resolved_user_id is None:
            raise RuntimeError(
                "Cannot persist SETTLEMENT entry: failed to resolve "
                f"user_id for member '{entry.member}'. This would bypass the dedup constraint."
            )

        row = LedgerEntryModel(
            circle_id=circle_id,
            id=entry.id,
            circle_month=entry.circle_month,
            tx_type=entry.tx_type.value,
            member=entry.member,
            user_id=resolved_user_id,
            amount=entry.amount,
            status=entry.status.value,
            debt_id=entry.debt_id,
            intended_for=entry.intended_for,
            note=entry.note,
            timestamp=entry.timestamp,
            idempotency_key=idempotency_key if idx == 0 else None,
        )
        db.add(row)

    db_members = getattr(engine, "_db_member_records", {})
    for name, member in engine.members.items():
        db_member = db_members.get(name)
        if not db_member:
            continue
        db_member.status = member.status.value.lower()
        db_member.missed_count = member.missed_count
        db_member.late_count = member.late_count
        db_member.has_received_payout = member.has_received_payout
        db_member.debts_penalized_json = list(member._debts_penalized)
