from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import uuid4

log = logging.getLogger("susucircle")


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
    contribution: float = 100.00
    late_fee_rate: float = 0.05
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
      status:          Payment verification status.
      debt_id:         For SETTLEMENT entries — the UUID of the ARREARS
                       entry being settled. None for all other types.
      intended_for:    For PAYOUT / ARREARS — who was supposed to receive
                       the pot that month. Eliminates schedule-index
                       assumptions.
      note:            Human-readable context.
      timestamp:       ISO 8601.
    """
    id: str
    circle_month: int
    tx_type: TxType
    member: str
    amount: float
    status: PaymentStatus
    debt_id: Optional[str] = None
    intended_for: Optional[str] = None
    note: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def __str__(self) -> str:
        sign = "+" if self.amount >= 0 else ""
        ref = f" [ref:{self.debt_id[:8]}]" if self.debt_id else ""
        target = f" ->{self.intended_for}" if self.intended_for else ""
        return (
            f"  M{self.circle_month:<2} [{self.tx_type.value:>22}] "
            f"{self.member:<12} {sign}{self.amount:>8.2f}  "
            f"({self.status.value}){ref}{target} {self.note}"
        )


# ---------------------------------------------------------------------------
# Member State (non-financial state only — balances computed from ledger)
# ---------------------------------------------------------------------------

@dataclass
class MemberRecord:
    name: str
    status: MemberStatus = MemberStatus.ACTIVE
    missed_count: int = 0
    late_count: int = 0
    has_received_payout: bool = False


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class SusuCircle:
    """
    Production-hardened ROSCA engine.

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

        self.config = config or CircleConfig()
        self.members: dict[str, MemberRecord] = {
            name: MemberRecord(name=name) for name in members
        }
        self.payout_schedule: list[str] = self._build_payout_order(members)
        self.total_cycles: int = len(members)
        self.current_month: int = 0
        self.ledger: list[LedgerEntry] = []
        self._escrow: float = 0.0

    def _build_payout_order(self, members: list[str]) -> list[str]:
        order = members[:]
        if self.config.payout_strategy in (PayoutStrategy.RANDOM, PayoutStrategy.BID):
            rng = random.Random(self.config.seed)
            rng.shuffle(order)
        return order

    def _append(self, **kwargs) -> LedgerEntry:
        """Create and append an immutable ledger entry."""
        entry = LedgerEntry(id=str(uuid4()), **kwargs)
        self.ledger.append(entry)
        return entry

    # -- Validation ----------------------------------------------------------

    def _validate_member(self, name: str) -> MemberRecord:
        if name not in self.members:
            raise ValueError(f"Unknown member: {name}")
        return self.members[name]

    def _validate_payment(self, name: str, amount: float, status: PaymentStatus):
        self._validate_member(name)
        if not isinstance(status, PaymentStatus):
            raise TypeError(f"status must be PaymentStatus, got {type(status)}")
        if amount < 0:
            raise ValueError(f"Negative amount from {name}: {amount}")

    # -- Ledger Queries (pure projections) -----------------------------------

    def get_member_balance(self, name: str) -> dict:
        """Compute a member's financial position from the ledger."""
        self._validate_member(name)
        contributed = sum(
            e.amount for e in self.ledger
            if e.member == name and e.tx_type in (
                TxType.CONTRIBUTION, TxType.LATE_CONTRIBUTION, TxType.LATE_FEE,
            )
        )
        received = sum(
            abs(e.amount) for e in self.ledger
            if e.member == name and e.amount < 0
        )
        penalties = sum(
            e.amount for e in self.ledger
            if e.member == name and e.tx_type == TxType.LATE_FEE
        )
        return {
            "contributed": round(contributed, 2),
            "received": round(received, 2),
            "penalties": round(penalties, 2),
            "net": round(contributed - received, 2),
        }

    def get_pending_arrears(self, member: str | None = None) -> list[LedgerEntry]:
        """
        Return arrears that have NOT been fully settled.

        An arrears entry is considered settled if SETTLEMENT entries
        referencing its ID sum to >= the original amount. No mutation needed.
        """
        # Build a map of total settled per debt_id
        settled_totals: dict[str, float] = {}
        for e in self.ledger:
            if e.tx_type == TxType.SETTLEMENT and e.debt_id is not None:
                settled_totals[e.debt_id] = settled_totals.get(e.debt_id, 0) + e.amount

        pending = []
        for e in self.ledger:
            if e.tx_type != TxType.ARREARS:
                continue
            if member is not None and e.member != member:
                continue
            total_settled = settled_totals.get(e.id, 0)
            if total_settled < e.amount:
                pending.append(e)
        return pending

    def get_partially_settled_amount(self, debt_id: str) -> float:
        """Sum of all partial settlements against a specific debt."""
        return sum(
            e.amount for e in self.ledger
            if e.tx_type == TxType.SETTLEMENT and e.debt_id == debt_id
        )

    # -- Core Cycle ----------------------------------------------------------

    def run_month(self, payments: dict[str, tuple[float, PaymentStatus]]) -> dict:
        """
        Execute one cycle.

        Args:
            payments: {member_name: (amount_paid, PaymentStatus)}
        """
        if self.current_month >= self.total_cycles:
            raise RuntimeError("All cycles already completed.")

        # Validate all inputs BEFORE modifying any state
        for name, (amount, status) in payments.items():
            self._validate_payment(name, amount, status)

        self.current_month += 1
        month = self.current_month
        pot = 0.0
        report: dict = {
            "month": month, "contributions": [], "arrears": [],
            "payout": {}, "warnings": [],
        }

        intended_recipient = self._next_eligible_recipient()

        log.info(f"\n{'='*60}")
        log.info(f"  MONTH {month} OF {self.total_cycles}")
        log.info(f"{'='*60}")

        # --- Collect contributions ------------------------------------------
        for name, record in self.members.items():
            if record.status == MemberStatus.REMOVED:
                continue

            payment_data = payments.get(name)
            if payment_data is None:
                amount, status = 0.0, PaymentStatus.FAILED
            else:
                amount, status = payment_data

            expected = self.config.contribution

            if status == PaymentStatus.VERIFIED and amount >= expected:
                pot += expected
                self._append(
                    circle_month=month, tx_type=TxType.CONTRIBUTION,
                    member=name, amount=expected, status=PaymentStatus.VERIFIED,
                )
                report["contributions"].append({"member": name, "amount": expected})
                log.info(f"  ✅ {name:<12} contributed ${expected:.2f}")

                if amount > expected:
                    overage = round(amount - expected, 2)
                    log.warning(f"  ⚠  {name} overpaid by ${overage:.2f} — excess ignored")
                    report["warnings"].append(f"{name} overpaid by ${overage:.2f}")

            elif status == PaymentStatus.VERIFIED and 0 < amount < expected:
                # Partial payment
                pot += amount
                self._append(
                    circle_month=month, tx_type=TxType.CONTRIBUTION,
                    member=name, amount=amount, status=PaymentStatus.VERIFIED,
                    note="partial",
                )
                shortfall = round(expected - amount, 2)
                self._append(
                    circle_month=month, tx_type=TxType.ARREARS,
                    member=name, amount=shortfall, status=PaymentStatus.PENDING,
                    intended_for=intended_recipient,
                    note=f"partial shortfall (paid {amount}, owed {expected})",
                )
                record.missed_count += 1
                report["contributions"].append({"member": name, "amount": amount})
                report["arrears"].append({"member": name, "amount": shortfall})
                log.info(
                    f"  ⚠  {name:<12} partial ${amount:.2f} / ${expected:.2f}"
                    f" — ${shortfall:.2f} as ARREARS"
                )

            else:
                # Full miss
                record.missed_count += 1
                self._append(
                    circle_month=month, tx_type=TxType.ARREARS,
                    member=name, amount=expected, status=PaymentStatus.PENDING,
                    intended_for=intended_recipient,
                    note="missed payment",
                )
                report["arrears"].append({"member": name, "amount": expected})

                warning = (
                    f"{name} MISSED — ${expected:.2f} as ARREARS "
                    f"(strike {record.missed_count}/{self.config.max_missed_before_suspend})"
                )
                log.warning(f"  ❌ {warning}")
                report["warnings"].append(warning)

                if record.missed_count >= self.config.max_missed_before_suspend:
                    record.status = MemberStatus.SUSPENDED
                    msg = f"{name} SUSPENDED after {record.missed_count} missed payments"
                    log.warning(f"  🚫 {msg}")
                    report["warnings"].append(msg)

        # --- Payout ---------------------------------------------------------
        if intended_recipient is None:
            self._escrow += pot
            self._append(
                circle_month=month, tx_type=TxType.POT_HELD,
                member="ESCROW", amount=pot, status=PaymentStatus.VERIFIED,
                note=f"no eligible recipient — total escrow: {self._escrow:.2f}",
            )
            log.warning(f"\n  🔒 No eligible recipient — ${pot:.2f} held in escrow")
            report["warnings"].append(f"Pot held in escrow: ${pot:.2f}")
            return report

        recipient = self.members[intended_recipient]
        payout_amount = round(pot, 2)
        active_count = sum(
            1 for r in self.members.values() if r.status != MemberStatus.REMOVED
        )
        full_pot = round(self.config.contribution * active_count, 2)

        self._append(
            circle_month=month, tx_type=TxType.PAYOUT,
            member=intended_recipient, amount=-payout_amount,
            status=PaymentStatus.VERIFIED,
            intended_for=intended_recipient,
            note=f"{'FULL' if payout_amount >= full_pot else f'SHORT by ${full_pot - payout_amount:.2f}'}",
        )
        recipient.has_received_payout = True

        report["payout"] = {
            "member": intended_recipient,
            "amount": payout_amount,
            "expected": full_pot,
        }

        if payout_amount < full_pot:
            log.info(
                f"\n  💰 PAYOUT → {intended_recipient}: ${payout_amount:.2f}"
                f" (SHORT by ${full_pot - payout_amount:.2f})"
            )
        else:
            log.info(f"\n  💰 PAYOUT → {intended_recipient}: ${payout_amount:.2f} (FULL)")

        return report

    def _next_eligible_recipient(self) -> str | None:
        for name in self.payout_schedule:
            record = self.members[name]
            if record.status == MemberStatus.ACTIVE and not record.has_received_payout:
                return name
        return None

    # -- Arrears Settlement --------------------------------------------------

    def settle_arrears(
        self,
        member: str,
        amount_paid: float | None = None,
        debt_id: str | None = None,
    ) -> dict | None:
        """
        Settle a pending debt. Supports full and partial settlement.

        Args:
            member:      The debtor's name.
            amount_paid: Cash received. If None, pays the full oldest debt.
                         If less than owed, records a partial settlement.
            debt_id:     Settle a specific debt by UUID. If None, FIFO.

        Returns:
            Settlement details, or None if no pending arrears.
        """
        record = self._validate_member(member)
        if amount_paid is not None and amount_paid <= 0:
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
            target = pending[0]

        owed = target.amount
        already_paid = self.get_partially_settled_amount(target.id)
        remaining = round(owed - already_paid, 2)

        if remaining <= 0:
            log.info(f"  ℹ️  Debt {target.id[:8]} already fully settled.")
            return None

        pay = amount_paid if amount_paid is not None else remaining
        pay = min(pay, remaining)
        is_full = (pay >= remaining)

        shorted_recipient = target.intended_for
        if shorted_recipient is None:
            raise RuntimeError(
                f"ARREARS entry {target.id[:8]} missing intended_for — data integrity issue"
            )

        # Late fee calculation
        late_fee = 0.0
        record.late_count += 1
        if record.late_count > self.config.grace_cycles:
            late_fee = round(pay * self.config.late_fee_rate, 2)

        total_required = round(pay + late_fee, 2)

        # 1. Settlement reference (no mutation of original ARREARS entry)
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
            note=f"settling {'all' if is_full else f'${pay:.2f} of ${remaining:.2f}'} from month {target.circle_month}",
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
            f"  ⚖️  {'SETTLED' if is_full else 'PARTIAL'}: {member} paid ${pay:.2f}"
            f"{f' + ${late_fee:.2f} fee' if late_fee > 0 else ''}"
            f" → {shorted_recipient}"
            f"{f' (${remaining - pay:.2f} still owed)' if not is_full else ''}"
        )

        return {
            "debtor": member,
            "creditor": shorted_recipient,
            "principal_paid": pay,
            "remaining": round(remaining - pay, 2),
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
        """Remove a member. Checks outstanding arrears before refunding."""
        record = self._validate_member(name)
        if record.status == MemberStatus.REMOVED:
            raise ValueError(f"{name} is already removed.")

        pending = self.get_pending_arrears(member=name)
        total_owed = sum(d.amount - self.get_partially_settled_amount(d.id) for d in pending)
        total_owed = round(total_owed, 2)

        if total_owed > 0:
            log.warning(
                f"  ⚠  {name} has ${total_owed:.2f} in outstanding arrears. "
                f"Deducting from refund."
            )

        record.status = MemberStatus.REMOVED
        result: dict = {"member": name, "action": "removed", "arrears_forfeited": total_owed}

        if refund and not record.has_received_payout:
            balance = self.get_member_balance(name)
            gross_refund = balance["contributed"]
            net_refund = max(round(gross_refund - total_owed, 2), 0)

            self._append(
                circle_month=self.current_month, tx_type=TxType.REMOVAL_REFUND,
                member=name, amount=-net_refund, status=PaymentStatus.VERIFIED,
                note=f"refund (gross: {gross_refund}, arrears deducted: {total_owed})",
            )

            # Mark forfeited arrears as settled
            for debt in pending:
                self._append(
                    circle_month=self.current_month, tx_type=TxType.SETTLEMENT,
                    member=name, amount=0, status=PaymentStatus.VERIFIED,
                    debt_id=debt.id,
                    note="forfeited on member removal",
                )

            result["refund"] = net_refund
            log.info(f"  🔄 {name} removed. Refund: ${net_refund:.2f}")
        else:
            reason = "already received payout" if record.has_received_payout else "no refund policy"
            log.info(f"  🔄 {name} removed. No refund ({reason}).")
            result["refund"] = 0

        if name in self.payout_schedule:
            self.payout_schedule = [n for n in self.payout_schedule if n != name]
            self.total_cycles = len(self.payout_schedule)

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
                remaining = round(p.amount - settled_so_far, 2)
                log.warning(
                    f"     {p.member} owes ${remaining:.2f} "
                    f"(of ${p.amount:.2f}) from month {p.circle_month} → {p.intended_for}"
                )

        report = {}
        all_balanced = True

        for name, r in self.members.items():
            bal = self.get_member_balance(name)
            icon = {"active": "✅", "suspended": "⏸ ", "removed": "❌"}[r.status.value]
            balance_note = "BALANCED" if bal["net"] == 0 else f"NET: {bal['net']:+.2f}"
            if bal["net"] != 0 and r.status == MemberStatus.ACTIVE:
                all_balanced = False

            log.info(
                f"  {icon} {name:<12} "
                f"in: ${bal['contributed']:>7.2f}  "
                f"out: ${bal['received']:>7.2f}  "
                f"fees: ${bal['penalties']:>5.2f}  "
                f"missed: {r.missed_count}  "
                f"→ {balance_note}"
            )
            report[name] = {**bal, "status": r.status.value, "missed": r.missed_count}

        if self._escrow > 0:
            log.warning(f"\n  🔒 Escrow balance: ${self._escrow:.2f}")

        if pending:
            log.warning(f"\n  ⚠  {len(pending)} debts outstanding.")
        elif all_balanced:
            log.info(f"\n  ✅ All members balanced. Circle is whole.")
        else:
            log.warning(f"\n  ⚠  Imbalances detected — review ledger.")

        report["_meta"] = {
            "balanced": all_balanced,
            "outstanding_arrears": len(pending),
            "escrow": self._escrow,
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
# Demo Scenarios
# ---------------------------------------------------------------------------

def demo_clean():
    log.info("\n" + "▓" * 60)
    log.info("  SCENARIO 1: CLEAN ROTATION")
    log.info("▓" * 60)

    c = SusuCircle(["Alice", "Bob", "Charlie"], CircleConfig(contribution=100))
    c.print_payout_schedule()

    for _ in range(3):
        c.run_month({
            "Alice": (100, PaymentStatus.VERIFIED),
            "Bob": (100, PaymentStatus.VERIFIED),
            "Charlie": (100, PaymentStatus.VERIFIED),
        })

    c.reconciliation_report()


def demo_arrears_settlement():
    log.info("\n" + "▓" * 60)
    log.info("  SCENARIO 2: ARREARS → SETTLEMENT → MADE WHOLE")
    log.info("▓" * 60)

    c = SusuCircle(
        ["Alice", "Bob", "Charlie"],
        CircleConfig(contribution=100, grace_cycles=1),
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

    bob_bal = c.get_member_balance("Bob")
    log.info(f"\n  📊 Bob received so far: ${bob_bal['received']:.2f} (expected $300)")

    log.info("\n--- Charlie settles arrears ---")
    c.settle_arrears("Charlie")

    c.run_month({
        "Alice": (100, PaymentStatus.VERIFIED),
        "Bob": (100, PaymentStatus.VERIFIED),
        "Charlie": (100, PaymentStatus.VERIFIED),
    })

    bob_bal = c.get_member_balance("Bob")
    log.info(f"\n  📊 Bob after settlement: ${bob_bal['received']:.2f}")

    c.reconciliation_report()
    c.print_full_ledger()


def demo_partial_payment():
    log.info("\n" + "▓" * 60)
    log.info("  SCENARIO 3: PARTIAL PAYMENT")
    log.info("▓" * 60)

    c = SusuCircle(
        ["Alice", "Bob", "Charlie"],
        CircleConfig(contribution=100, grace_cycles=0),
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
        "Charlie": (60, PaymentStatus.VERIFIED),
    })

    pending = c.get_pending_arrears("Charlie")
    log.info(f"\n  📊 Charlie's pending arrears: {len(pending)} entries")
    for p in pending:
        log.info(f"     ${p.amount:.2f} from month {p.circle_month}")

    log.info("\n--- Charlie settles partial arrears ---")
    c.settle_arrears("Charlie")

    c.run_month({
        "Alice": (100, PaymentStatus.VERIFIED),
        "Bob": (100, PaymentStatus.VERIFIED),
        "Charlie": (100, PaymentStatus.VERIFIED),
    })

    c.reconciliation_report()
    c.print_full_ledger()


def demo_partial_settlement():
    log.info("\n" + "▓" * 60)
    log.info("  SCENARIO 4: PARTIAL SETTLEMENT (INSTALLMENTS)")
    log.info("▓" * 60)

    c = SusuCircle(
        ["Alice", "Bob", "Charlie"],
        CircleConfig(contribution=100, grace_cycles=0),
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

    log.info("\n--- Charlie pays $40 of $100 debt ---")
    result = c.settle_arrears("Charlie", amount_paid=40)
    log.info(f"  Remaining: ${result['remaining']:.2f}")

    log.info("\n--- Charlie pays remaining $60 ---")
    result = c.settle_arrears("Charlie", amount_paid=60)
    log.info(f"  Fully settled: {result['fully_settled']}")

    c.run_month({
        "Alice": (100, PaymentStatus.VERIFIED),
        "Bob": (100, PaymentStatus.VERIFIED),
        "Charlie": (100, PaymentStatus.VERIFIED),
    })

    c.reconciliation_report()
    c.print_full_ledger()


def demo_escrow():
    log.info("\n" + "▓" * 60)
    log.info("  SCENARIO 5: ESCROW (SUSPENDED MEMBER'S TURN)")
    log.info("▓" * 60)

    c = SusuCircle(
        ["Alice", "Bob", "Charlie"],
        CircleConfig(contribution=100, max_missed_before_suspend=2),
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

    c.run_month({
        "Alice": (100, PaymentStatus.VERIFIED),
        "Bob": (100, PaymentStatus.VERIFIED),
        "Charlie": (0, PaymentStatus.FAILED),
    })

    c.reconciliation_report()
    c.print_full_ledger()


def demo_removal_with_arrears():
    log.info("\n" + "▓" * 60)
    log.info("  SCENARIO 6: REMOVAL WITH OUTSTANDING ARREARS")
    log.info("▓" * 60)

    c = SusuCircle(
        ["Alice", "Bob", "Charlie", "Diana"],
        CircleConfig(contribution=100),
    )
    c.print_payout_schedule()

    c.run_month({
        "Alice": (100, PaymentStatus.VERIFIED),
        "Bob": (100, PaymentStatus.VERIFIED),
        "Charlie": (100, PaymentStatus.VERIFIED),
        "Diana": (100, PaymentStatus.VERIFIED),
    })

    c.run_month({
        "Alice": (100, PaymentStatus.VERIFIED),
        "Bob": (100, PaymentStatus.VERIFIED),
        "Charlie": (0, PaymentStatus.FAILED),
        "Diana": (100, PaymentStatus.VERIFIED),
    })

    log.info("\n--- Removing Charlie (owes $100) ---")
    result = c.remove_member("Charlie", refund=True)
    log.info(f"  Refund: ${result['refund']:.2f} (contributed $100, owed $100)")

    for _ in range(c.total_cycles - c.current_month):
        c.run_month({
            "Alice": (100, PaymentStatus.VERIFIED),
            "Bob": (100, PaymentStatus.VERIFIED),
            "Diana": (100, PaymentStatus.VERIFIED),
        })

    c.reconciliation_report()


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
    log.info("║      SUSUCIRCLE — ROSCA ENGINE v0.3                     ║")
    log.info("║      Production-Hardened (Post Code Review)             ║")
    log.info("╚══════════════════════════════════════════════════════════╝")

    demo_clean()
    demo_arrears_settlement()
    demo_partial_payment()
    demo_partial_settlement()
    demo_escrow()
    demo_removal_with_arrears()

    log.info("\n\n" + "=" * 60)
    log.info("  ✅ ALL SCENARIOS COMPLETE — v0.3")
    log.info("=" * 60)
    log.info("  Fixes from code review:")
    log.info("    1. ✅ Immutable ledger — no in-place mutations")
    log.info("    2. ✅ UUID on every entry — referential integrity")
    log.info("    3. ✅ Input validation on all public methods")
    log.info("    4. ✅ Partial payments create proportional arrears")
    log.info("    5. ✅ Partial settlements supported")
    log.info("    6. ✅ POT_HELD for escrow tracking")
    log.info("    7. ✅ Late fees as explicit cash requirement")
    log.info("    8. ✅ remove_member deducts outstanding arrears")
    log.info("    9. ✅ Frozen config (immutable)")
    log.info("   10. ✅ Logging replaces print")
    log.info("   11. ✅ intended_for on ARREARS (no index assumptions)")
    log.info("   12. ✅ Balances computed from ledger (single source of truth)")
