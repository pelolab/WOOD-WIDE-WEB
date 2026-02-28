"""
SUSUCIRCLE — ROSCA ENGINE v0.4
Production-Hardened (Post Code Review)

Fixes from v0.3 → v0.4:
  #1  get_member_balance: contributed and penalties are now disjoint
  #2  settle_arrears: late_count increments once per debt, not per settlement call
  #3  run_month: two-pass recipient resolution — ARREARS.intended_for is always correct
  #4  Fixed temporal horizon — remove_member no longer shrinks total_cycles
  #6  Escrow derived from ledger via @property (no mutable _escrow field)
  #8  ESCROW_SENTINEL constant replaces magic string "ESCROW"
  #10 UTC timestamps on all ledger entries
  #12 Decimal precision throughout (no float currency)
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Optional
from uuid import uuid4

log = logging.getLogger("susucircle")

# ---------------------------------------------------------------------------
# Financial Constants
# ---------------------------------------------------------------------------

CENT = Decimal('0.01')
ESCROW_SENTINEL = "SYSTEM_ESCROW"


def to_decimal(value) -> Decimal:
    """Standardized financial rounding."""
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class PayoutStrategy(Enum):
    FIXED = "fixed"
    RANDOM = "random"
    BID = "bid"


class PaymentStatus(Enum):
    VERIFIED = "verified"
    FAILED = "failed"
    PENDING = "pending"


class MemberStatus(Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REMOVED = "removed"


class TxType(Enum):
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


# ---------------------------------------------------------------------------
# Configuration (frozen — immutable after creation)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CircleConfig:
    contribution: Decimal = Decimal('100.00')
    late_fee_rate: Decimal = Decimal('0.05')
    max_missed_before_suspend: int = 2
    grace_cycles: int = 1
    payout_strategy: PayoutStrategy = PayoutStrategy.FIXED
    seed: Optional[int] = None


# ---------------------------------------------------------------------------
# Ledger Entry (frozen — truly immutable)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LedgerEntry:
    """
    Immutable record. Once appended to the ledger, it is never modified.

    Fields:
      id:              Unique identifier (UUID).
      circle_month:    The cycle number when this event occurred.
      tx_type:         What kind of financial event this is.
      member:          The member this entry belongs to.
      amount:          Positive for inflows (contributions, fees paid),
                       negative for outflows (payouts, refunds).
                       Uses Decimal for precision.
      status:          Payment verification status.
      debt_id:         For SETTLEMENT entries — the UUID of the ARREARS
                       entry being settled. None for all other types.
      intended_for:    For PAYOUT / ARREARS — who was supposed to receive
                       the pot that month. Eliminates schedule-index
                       assumptions.
      note:            Human-readable context.
      timestamp:       ISO 8601 (UTC).
    """
    id: str
    circle_month: int
    tx_type: TxType
    member: str
    amount: Decimal
    status: PaymentStatus
    debt_id: Optional[str] = None
    intended_for: Optional[str] = None
    note: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __str__(self) -> str:
        sign = "+" if self.amount >= 0 else ""
        ref = f" [ref:{self.debt_id[:8]}]" if self.debt_id else ""
        target = f" ->{self.intended_for}" if self.intended_for else ""
        return (
            f"  M{self.circle_month:<2} [{self.tx_type.value:>22}] "
            f"{self.member:<12} {sign}{self.amount:>8}  "
            f"({self.status.value}){ref}{target} {self.note}"
        )


# ---------------------------------------------------------------------------
# Member State (non-financial state only — balances computed from ledger)
# ---------------------------------------------------------------------------

@dataclass
class MemberRecord:
    """
    Non-financial member state. Balances are computed from the ledger.

    _debts_penalized tracks which ARREARS debt_ids have already incremented
    late_count, preventing multiple partial settlements on the same debt
    from inflating the strike counter. (Fix #2)
    """
    name: str
    status: MemberStatus = MemberStatus.ACTIVE
    missed_count: int = 0
    late_count: int = 0
    has_received_payout: bool = False
    _debts_penalized: set[str] = field(default_factory=set)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class SusuCircle:
    """
    Production-hardened ROSCA engine (v0.4).

    The ledger is the single source of truth. MemberRecord holds only
    non-financial state (status, strike counts). All financial totals
    are computed from the ledger on demand.

    NOT thread-safe. In a multi-user environment, wrap all public
    methods in a database transaction or application-level lock.
    """

    def __init__(self, members: list[str], config: CircleConfig | None = None):
        if len(members) < 2:
            raise ValueError("A Susu circle needs at least 2 members.")
        if len(members) != len(set(members)):
            raise ValueError("Duplicate member names not allowed.")
        if any(m == ESCROW_SENTINEL for m in members):
            raise ValueError(f"'{ESCROW_SENTINEL}' is reserved and cannot be a member name.")

        self.config = config or CircleConfig()
        self.members: dict[str, MemberRecord] = {
            name: MemberRecord(name=name) for name in members
        }
        self.payout_schedule: list[str] = self._build_payout_order(members)
        self.original_member_count: int = len(members)  # FIX #4: Fixed temporal horizon
        self.current_month: int = 0
        self.ledger: list[LedgerEntry] = []

    # -- FIX #6: Escrow derived from ledger (no mutable _escrow field) ------

    @property
    def escrow(self) -> Decimal:
        """Compute escrow balance from POT_HELD ledger entries."""
        return sum(
            (e.amount for e in self.ledger if e.tx_type == TxType.POT_HELD),
            Decimal('0.00'),
        )

    def _build_payout_order(self, members: list[str]) -> list[str]:
        order = members[:]
        if self.config.payout_strategy in (PayoutStrategy.RANDOM, PayoutStrategy.BID):
            rng = random.Random(self.config.seed)
            rng.shuffle(order)
        return order

    def _append(self, **kwargs) -> LedgerEntry:
        """Create and append an immutable ledger entry."""
        kwargs.setdefault('circle_month', self.current_month)
        kwargs.setdefault('status', PaymentStatus.VERIFIED)
        entry = LedgerEntry(id=str(uuid4()), **kwargs)
        self.ledger.append(entry)
        return entry

    def _copy_with_recipient(self, entry: LedgerEntry, recipient: str | None) -> LedgerEntry:
        """Replace intended_for on a frozen LedgerEntry. Preserves original id."""
        return LedgerEntry(
            id=entry.id,
            circle_month=entry.circle_month,
            tx_type=entry.tx_type,
            member=entry.member,
            amount=entry.amount,
            status=entry.status,
            debt_id=entry.debt_id,
            intended_for=recipient,
            note=entry.note,
            timestamp=entry.timestamp,
        )

    # -- Validation ----------------------------------------------------------

    def _validate_member(self, name: str) -> MemberRecord:
        if name not in self.members:
            raise ValueError(f"Unknown member: {name}")
        return self.members[name]

    def _validate_payment(self, name: str, amount: Decimal, status: PaymentStatus):
        self._validate_member(name)
        if not isinstance(status, PaymentStatus):
            raise TypeError(f"status must be PaymentStatus, got {type(status)}")
        if amount < 0:
            raise ValueError(f"Negative amount from {name}: {amount}")

    # -- Ledger Queries (pure projections) -----------------------------------

    def get_member_balance(self, name: str) -> dict:
        """
        Compute a member's financial position from the ledger.

        FIX #1: contributed and penalties are now disjoint.
          contributed: CONTRIBUTION + LATE_CONTRIBUTION (principal paid in)
          penalties:   LATE_FEE (fee cash paid in, separate from principal)
          received:    all negative-amount entries (payouts, refunds, compensation)
          net:         (contributed + penalties) - received
        """
        self._validate_member(name)
        zero = Decimal('0.00')

        contributed = sum(
            (e.amount for e in self.ledger
             if e.member == name and e.tx_type in (
                 TxType.CONTRIBUTION, TxType.LATE_CONTRIBUTION,
             )),
            zero,
        )
        penalties = sum(
            (e.amount for e in self.ledger
             if e.member == name and e.tx_type == TxType.LATE_FEE),
            zero,
        )
        received = sum(
            (abs(e.amount) for e in self.ledger
             if e.member == name and e.amount < zero),
            zero,
        )

        return {
            "contributed": contributed,
            "penalties": penalties,
            "received": received,
            "net": (contributed + penalties) - received,
        }

    def get_pending_arrears(self, member: str | None = None) -> list[LedgerEntry]:
        """
        Return arrears that have NOT been fully settled.

        An arrears entry is considered settled if SETTLEMENT entries
        referencing its ID sum to >= the original amount.
        """
        settled_totals: dict[str, Decimal] = {}
        for e in self.ledger:
            if e.tx_type == TxType.SETTLEMENT and e.debt_id is not None:
                settled_totals[e.debt_id] = settled_totals.get(e.debt_id, Decimal('0.00')) + e.amount

        pending = []
        for e in self.ledger:
            if e.tx_type != TxType.ARREARS:
                continue
            if member is not None and e.member != member:
                continue
            total_settled = settled_totals.get(e.id, Decimal('0.00'))
            if total_settled < e.amount:
                pending.append(e)
        return pending

    def get_partially_settled_amount(self, debt_id: str) -> Decimal:
        """Sum of all partial settlements against a specific debt."""
        return sum(
            (e.amount for e in self.ledger
             if e.tx_type == TxType.SETTLEMENT and e.debt_id == debt_id),
            Decimal('0.00'),
        )

    # -- Core Cycle ----------------------------------------------------------

    def run_month(self, payments: dict[str, tuple[Decimal | float | int, PaymentStatus]]) -> dict:
        """
        Execute one cycle.

        FIX #3: Two-pass recipient resolution.
          Pass 1: Collect contributions, stage ARREARS with intended_for=None
          Pass 2: Resolve recipient AFTER all status changes
          Pass 3: Backfill intended_for on staged ARREARS entries
          Pass 4: Payout

        FIX #4: Uses original_member_count as fixed temporal horizon.

        Args:
            payments: {member_name: (amount_paid, PaymentStatus)}
        """
        if self.current_month >= self.original_member_count:
            raise RuntimeError("Circle has reached its fixed temporal horizon.")

        # Validate all inputs BEFORE modifying any state
        for name, (amount, status) in payments.items():
            self._validate_payment(name, to_decimal(amount), status)

        self.current_month += 1
        month = self.current_month
        pot = Decimal('0.00')
        cycle_arrears_indices: list[int] = []
        report: dict = {
            "month": month, "contributions": [], "arrears": [],
            "payout": {}, "warnings": [],
        }

        log.info(f"\n{'='*60}")
        log.info(f"  MONTH {month} OF {self.original_member_count}")
        log.info(f"{'='*60}")

        # --- PASS 1: Collect contributions ----------------------------------
        for name, record in self.members.items():
            if record.status == MemberStatus.REMOVED:
                continue

            payment_data = payments.get(name)
            if payment_data is None:
                d_amt, status = Decimal('0.00'), PaymentStatus.FAILED
            else:
                d_amt, status = to_decimal(payment_data[0]), payment_data[1]

            expected = self.config.contribution

            if status == PaymentStatus.VERIFIED and d_amt >= expected:
                pot += expected
                self._append(
                    circle_month=month, tx_type=TxType.CONTRIBUTION,
                    member=name, amount=expected, status=PaymentStatus.VERIFIED,
                )
                report["contributions"].append({"member": name, "amount": expected})
                log.info(f"  ✅ {name:<12} contributed ${expected}")

                if d_amt > expected:
                    overage = to_decimal(d_amt - expected)
                    log.warning(f"  ⚠  {name} overpaid by ${overage} — excess ignored")
                    report["warnings"].append(f"{name} overpaid by ${overage}")

            elif status == PaymentStatus.VERIFIED and d_amt > Decimal('0.00'):
                # Partial payment — credit what was paid, arrears for the rest
                pot += d_amt
                self._append(
                    circle_month=month, tx_type=TxType.CONTRIBUTION,
                    member=name, amount=d_amt, status=PaymentStatus.VERIFIED,
                    note="partial",
                )
                shortfall = to_decimal(expected - d_amt)
                # Stage ARREARS with intended_for=None (resolved in Pass 3)
                self._append(
                    circle_month=month, tx_type=TxType.ARREARS,
                    member=name, amount=shortfall, status=PaymentStatus.PENDING,
                    intended_for=None,
                    note=f"partial shortfall (paid {d_amt}, owed {expected})",
                )
                cycle_arrears_indices.append(len(self.ledger) - 1)
                record.missed_count += 1
                report["contributions"].append({"member": name, "amount": d_amt})
                report["arrears"].append({"member": name, "amount": shortfall})
                log.info(
                    f"  ⚠  {name:<12} partial ${d_amt} / ${expected}"
                    f" — ${shortfall} as ARREARS"
                )

            else:
                # Full miss
                record.missed_count += 1
                self._append(
                    circle_month=month, tx_type=TxType.ARREARS,
                    member=name, amount=expected, status=PaymentStatus.PENDING,
                    intended_for=None,
                    note="missed payment",
                )
                cycle_arrears_indices.append(len(self.ledger) - 1)
                report["arrears"].append({"member": name, "amount": expected})

                warning = (
                    f"{name} MISSED — ${expected} as ARREARS "
                    f"(strike {record.missed_count}/{self.config.max_missed_before_suspend})"
                )
                log.warning(f"  ❌ {warning}")
                report["warnings"].append(warning)

                if record.missed_count >= self.config.max_missed_before_suspend:
                    record.status = MemberStatus.SUSPENDED
                    msg = f"{name} SUSPENDED after {record.missed_count} missed payments"
                    log.warning(f"  🚫 {msg}")
                    report["warnings"].append(msg)

        # --- PASS 2: Resolve recipient AFTER all status changes -------------
        intended_recipient = self._next_eligible_recipient()

        # --- PASS 3: Backfill intended_for on staged ARREARS ----------------
        for idx in cycle_arrears_indices:
            self.ledger[idx] = self._copy_with_recipient(
                self.ledger[idx], intended_recipient,
            )

        # --- PASS 4: Payout -------------------------------------------------
        if intended_recipient is None:
            self._append(
                circle_month=month, tx_type=TxType.POT_HELD,
                member=ESCROW_SENTINEL, amount=pot, status=PaymentStatus.VERIFIED,
                note="no eligible recipient",
            )
            log.warning(f"\n  🔒 No eligible recipient — ${pot} held in escrow")
            report["warnings"].append(f"Pot held in escrow: ${pot}")
            report["payout"] = None
            report["escrowed"] = pot
            return report

        recipient = self.members[intended_recipient]
        payout_amount = pot
        active_count = sum(
            1 for r in self.members.values() if r.status != MemberStatus.REMOVED
        )
        full_pot = to_decimal(self.config.contribution * active_count)

        self._append(
            circle_month=month, tx_type=TxType.PAYOUT,
            member=intended_recipient, amount=-payout_amount,
            status=PaymentStatus.VERIFIED,
            intended_for=intended_recipient,
            note=f"{'FULL' if payout_amount >= full_pot else f'SHORT by ${to_decimal(full_pot - payout_amount)}'}",
        )
        recipient.has_received_payout = True

        report["payout"] = {
            "member": intended_recipient,
            "amount": payout_amount,
            "expected": full_pot,
        }

        if payout_amount < full_pot:
            log.info(
                f"\n  💰 PAYOUT → {intended_recipient}: ${payout_amount}"
                f" (SHORT by ${to_decimal(full_pot - payout_amount)})"
            )
        else:
            log.info(f"\n  💰 PAYOUT → {intended_recipient}: ${payout_amount} (FULL)")

        return report

    def _next_eligible_recipient(self) -> str | None:
        for name in self.payout_schedule:
            if self._is_member_eligible_for_payout(name):
                return name
        return None

    def _is_member_eligible_for_payout(self, name: str) -> bool:
        record = self.members[name]
        return record.status == MemberStatus.ACTIVE and not record.has_received_payout

    # -- Arrears Settlement --------------------------------------------------

    def settle_arrears(
        self,
        member: str,
        amount_paid: Decimal | float | int | None = None,
        debt_id: str | None = None,
    ) -> dict | None:
        """
        Settle a pending debt. Supports full and partial settlement.

        FIX #2: late_count increments once per debt (tracked via
        _debts_penalized), not once per settlement call.

        Args:
            member:      The debtor's name.
            amount_paid: Cash received. If None, pays the full oldest debt.
                         If less than owed, records a partial settlement.
            debt_id:     Settle a specific debt by UUID. If None, FIFO.

        Returns:
            Settlement details, or None if no pending arrears.
        """
        record = self._validate_member(member)
        if amount_paid is not None:
            amount_paid = to_decimal(amount_paid)
            if amount_paid <= 0:
                raise ValueError(f"Settlement amount must be positive, got {amount_paid}")

        pending = self.get_pending_arrears(member=member)
        if not pending:
            log.info(f"  ℹ️  {member} has no pending arrears.")
            return None

        if debt_id:
            target = next((d for d in pending if d.id == debt_id), None)
            if target is None:
                raise ValueError(f"No pending debt with id {debt_id} for {member}")
        else:
            target = pending[0]  # FIFO

        already_paid = self.get_partially_settled_amount(target.id)
        remaining = to_decimal(target.amount - already_paid)

        if remaining <= 0:
            log.info(f"  ℹ️  Debt {target.id[:8]} already fully settled.")
            return None

        pay = min(amount_paid, remaining) if amount_paid is not None else remaining
        is_full = (pay >= remaining)

        shorted_recipient = target.intended_for
        if shorted_recipient is None:
            raise RuntimeError(
                f"ARREARS entry {target.id[:8]} missing intended_for — data integrity issue"
            )

        # --- FIX #2: One late strike per debt, not per settlement call ------
        late_fee = Decimal('0.00')
        if target.id not in record._debts_penalized:
            record._debts_penalized.add(target.id)
            record.late_count += 1
            if record.late_count > self.config.grace_cycles:
                late_fee = to_decimal(pay * self.config.late_fee_rate)

        total_required = to_decimal(pay + late_fee)

        # 1. Settlement reference
        self._append(
            circle_month=self.current_month, tx_type=TxType.SETTLEMENT,
            member=member, amount=pay, status=PaymentStatus.VERIFIED,
            debt_id=target.id,
            note=f"{'full' if is_full else 'partial'} settlement of debt from month {target.circle_month}",
        )

        # 2. Late contribution (cash in)
        self._append(
            circle_month=self.current_month, tx_type=TxType.LATE_CONTRIBUTION,
            member=member, amount=pay, status=PaymentStatus.VERIFIED,
            note=f"settling {'all' if is_full else f'{pay} of {remaining}'} from month {target.circle_month}",
        )

        # 3. Late fee (if applicable)
        if late_fee > 0:
            self._append(
                circle_month=self.current_month, tx_type=TxType.LATE_FEE,
                member=member, amount=late_fee, status=PaymentStatus.VERIFIED,
                note=f"late strike {record.late_count} (grace: {self.config.grace_cycles})",
            )

        # 4. Route principal to shorted member
        self._append(
            circle_month=self.current_month, tx_type=TxType.DELAYED_PAYOUT,
            member=shorted_recipient, amount=-pay,
            status=PaymentStatus.VERIFIED,
            debt_id=target.id,
            note=f"owed from month {target.circle_month} by {member}",
        )

        # 5. Route late fee compensation to shorted member
        if late_fee > 0:
            self._append(
                circle_month=self.current_month, tx_type=TxType.LATE_FEE_COMPENSATION,
                member=shorted_recipient, amount=-late_fee,
                status=PaymentStatus.VERIFIED,
                note=f"compensation from {member}'s late fee",
            )

        log.info(
            f"  ⚖️  {'SETTLED' if is_full else 'PARTIAL'}: {member} paid ${pay}"
            f"{f' + ${late_fee} fee' if late_fee > 0 else ''}"
            f" → {shorted_recipient}"
            f"{f' (${to_decimal(remaining - pay)} still owed)' if not is_full else ''}"
        )

        return {
            "debtor": member,
            "creditor": shorted_recipient,
            "principal_paid": pay,
            "remaining": to_decimal(remaining - pay),
            "late_fee": late_fee,
            "total_cash": total_required,
            "debt_id": target.id,
            "fully_settled": is_full,
            "from_month": target.circle_month,
            "settled_in_month": self.current_month,
        }

    def settle_all_arrears(self, member: str) -> list[dict]:
        """Settle all pending arrears for a member, oldest first."""
        settlements = []
        while True:
            result = self.settle_arrears(member)
            if result is None:
                break
            settlements.append(result)
        return settlements

    # -- Member Management ---------------------------------------------------

    def remove_member(self, name: str, refund: bool = True) -> dict:
        """
        Remove a member. Checks outstanding arrears before refunding.

        FIX #4: Does NOT modify original_member_count. The payout_schedule
        is updated to skip the removed member, but the temporal horizon
        remains fixed.
        """
        record = self._validate_member(name)
        if record.status == MemberStatus.REMOVED:
            raise ValueError(f"{name} is already removed.")

        pending = self.get_pending_arrears(member=name)
        total_owed = sum(
            to_decimal(d.amount - self.get_partially_settled_amount(d.id))
            for d in pending
        )

        if total_owed > 0:
            log.warning(
                f"  ⚠  {name} has ${total_owed} in outstanding arrears. "
                f"Deducting from refund."
            )

        record.status = MemberStatus.REMOVED
        result: dict = {"member": name, "action": "removed", "arrears_forfeited": total_owed}

        if refund and not record.has_received_payout:
            balance = self.get_member_balance(name)
            gross_refund = balance["contributed"]
            net_refund = max(to_decimal(gross_refund - total_owed), Decimal('0.00'))

            self._append(
                circle_month=self.current_month, tx_type=TxType.REMOVAL_REFUND,
                member=name, amount=-net_refund, status=PaymentStatus.VERIFIED,
                note=f"refund (gross: {gross_refund}, arrears deducted: {total_owed})",
            )

            # Mark forfeited arrears as settled for reporting/reconciliation.
            for debt in pending:
                debt_remaining = to_decimal(debt.amount - self.get_partially_settled_amount(debt.id))
                if debt_remaining <= 0:
                    continue
                self._append(
                    circle_month=self.current_month, tx_type=TxType.SETTLEMENT,
                    member=name, amount=debt_remaining, status=PaymentStatus.VERIFIED,
                    debt_id=debt.id,
                    note="forfeited on member removal",
                )

            result["refund"] = net_refund
            log.info(f"  🔄 {name} removed. Refund: ${net_refund}")
        else:
            reason = "already received payout" if record.has_received_payout else "no refund policy"
            log.info(f"  🔄 {name} removed. No refund ({reason}).")
            result["refund"] = Decimal('0.00')

        # Remove from payout schedule but do NOT change original_member_count
        if name in self.payout_schedule:
            self.payout_schedule = [n for n in self.payout_schedule if n != name]

        return result

    # -- Reporting -----------------------------------------------------------

    def reconciliation_report(self) -> dict:
        pending = self.get_pending_arrears()

        log.info(f"\n{'='*60}")
        log.info("  RECONCILIATION REPORT")
        log.info(f"{'='*60}")

        if pending:
            log.warning(f"\n  ⚠  OUTSTANDING ARREARS ({len(pending)}):")
            for p in pending:
                settled_so_far = self.get_partially_settled_amount(p.id)
                p_remaining = to_decimal(p.amount - settled_so_far)
                log.warning(
                    f"     {p.member} owes ${p_remaining} "
                    f"(of ${p.amount}) from month {p.circle_month} → {p.intended_for}"
                )

        report = {}
        all_balanced = True

        for name, r in self.members.items():
            bal = self.get_member_balance(name)
            icon = {"active": "✅", "suspended": "⏸ ", "removed": "❌"}[r.status.value]
            balance_note = "BALANCED" if bal["net"] == 0 else f"NET: {bal['net']:+}"
            if bal["net"] != 0 and r.status == MemberStatus.ACTIVE:
                all_balanced = False

            log.info(
                f"  {icon} {name:<12} "
                f"in: ${bal['contributed']:>7}  "
                f"out: ${bal['received']:>7}  "
                f"fees: ${bal['penalties']:>5}  "
                f"missed: {r.missed_count}  "
                f"→ {balance_note}"
            )
            report[name] = {**bal, "status": r.status.value, "missed": r.missed_count}

        current_escrow = self.escrow
        if current_escrow > 0:
            log.warning(f"\n  🔒 Escrow balance: ${current_escrow}")

        if pending:
            log.warning(f"\n  ⚠  {len(pending)} debts outstanding.")
        elif all_balanced:
            log.info(f"\n  ✅ All members balanced. Circle is whole.")
        else:
            log.warning(f"\n  ⚠  Imbalances detected — review ledger.")

        report["_meta"] = {
            "balanced": all_balanced,
            "outstanding_arrears": len(pending),
            "escrow": current_escrow,
        }
        return report

    def print_full_ledger(self) -> None:
        log.info(f"\n{'='*60}")
        log.info("  FULL AUDIT LEDGER")
        log.info(f"{'='*60}")
        for entry in self.ledger:
            log.info(str(entry))
        log.info(f"\n  Total entries: {len(self.ledger)}")

    def print_payout_schedule(self) -> None:
        log.info(f"\n{'='*60}")
        log.info(f"  PAYOUT SCHEDULE ({self.config.payout_strategy.value})")
        log.info(f"{'='*60}")
        for i, name in enumerate(self.payout_schedule):
            r = self.members[name]
            status = "✅ received" if r.has_received_payout else "⏳ pending"
            extra = f" [{r.status.value}]" if r.status != MemberStatus.ACTIVE else ""
            log.info(f"  {i+1}. {name:<12} {status}{extra}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        handlers=[logging.StreamHandler()],
    )

    log.info("╔══════════════════════════════════════════════════════════╗")
    log.info("║      SUSUCIRCLE — ROSCA ENGINE v0.4                     ║")
    log.info("║      Production-Hardened (Post Code Review)             ║")
    log.info("╚══════════════════════════════════════════════════════════╝")

    # Quick smoke test
    c = SusuCircle(
        ["Alice", "Bob", "Charlie"],
        CircleConfig(contribution=Decimal('100.00'), grace_cycles=1),
    )
    c.print_payout_schedule()

    c.run_month({
        "Alice": (100, PaymentStatus.VERIFIED),
        "Bob": (100, PaymentStatus.VERIFIED),
        "Charlie": (100, PaymentStatus.VERIFIED),
    })
    c.run_month({
        "Alice": (100, PaymentStatus.VERIFIED),
        "Bob": (100, PaymentStatus.VERIFIED),
        "Charlie": (0, PaymentStatus.FAILED),
    })
    c.settle_arrears("Charlie")
    c.run_month({
        "Alice": (100, PaymentStatus.VERIFIED),
        "Bob": (100, PaymentStatus.VERIFIED),
        "Charlie": (100, PaymentStatus.VERIFIED),
    })

    c.reconciliation_report()
    c.print_full_ledger()

    log.info("\n" + "=" * 60)
    log.info("  ✅ v0.4 SMOKE TEST COMPLETE")
    log.info("=" * 60)
    log.info("  Fixes applied:")
    log.info("    #1  ✅ get_member_balance: contributed/penalties disjoint")
    log.info("    #2  ✅ settle_arrears: late_count per debt, not per call")
    log.info("    #3  ✅ run_month: two-pass recipient resolution")
    log.info("    #4  ✅ Fixed temporal horizon (original_member_count)")
    log.info("    #6  ✅ Escrow derived from ledger (@property)")
    log.info("    #8  ✅ ESCROW_SENTINEL replaces magic string")
    log.info("   #10  ✅ UTC timestamps")
    log.info("   #12  ✅ Decimal precision throughout")
