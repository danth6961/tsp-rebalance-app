"""
ift_state_machine.py — single-writer IFT state management.

Owns IFT eligibility checks and the only code path that may mutate
IFT counters, last IFT date, or transaction audit rows.

Does not own scoring, regime selection, UI, or config I/O.
"""

from dataclasses import dataclass
from datetime import date
from typing import Dict, Optional

from storage import load_state_for_today, save_state, append_transaction_row

# Tolerance for normalize-to-100 rounding drift in engine.py.
G_MOVE_TOLERANCE_PCT = 0.5

MONTHLY_IFT_LIMIT = 2


def is_pure_g_move(target_alloc: Dict[str, float]) -> bool:
    """Return True if the target allocation is effectively 100% G Fund."""
    g = float(target_alloc.get("G", 0.0))
    others = sum(float(target_alloc.get(f, 0.0)) for f in ("C", "I", "S", "F"))
    return abs(g - 100.0) <= G_MOVE_TOLERANCE_PCT and others <= G_MOVE_TOLERANCE_PCT


@dataclass
class IFTDecision:
    """Result of an IFT eligibility check."""
    allowed: bool
    reason: str
    is_safety_move: bool = False


class IFTStateMachine:
    """Enforce that IFT state changes only happen through confirm()."""

    def __init__(self, state: Dict, today: date):
        # Roll over monthly state on every load.
        self.state = state
        self.today = today

    @classmethod
    def load(cls, today: date) -> "IFTStateMachine":
        """Load state from disk with month rollover applied."""
        return cls(load_state_for_today(today), today)

    @property
    def ift_count_this_month(self) -> int:
        return int(self.state.get("ift_count_this_month", 0))

    @property
    def last_ift_date(self) -> Optional[date]:
        raw = self.state.get("last_ift_date")
        return date.fromisoformat(raw) if raw else None

    def can_confirm(self, target_alloc: Dict[str, float]) -> IFTDecision:
        """Check whether a manual IFT can be confirmed without mutating state."""
        if is_pure_g_move(target_alloc):
            return IFTDecision(
                allowed=True,
                reason="G Fund safety move (does not count toward monthly cap)",
                is_safety_move=True,
            )

        if self.ift_count_this_month >= MONTHLY_IFT_LIMIT:
            return IFTDecision(
                allowed=False,
                reason=f"Monthly IFT limit of {MONTHLY_IFT_LIMIT} already reached",
            )

        return IFTDecision(allowed=True, reason="Within monthly IFT allowance")

    def confirm(self, current_alloc: Dict[str, float], target_alloc: Dict[str, float], regime: str) -> IFTDecision:
        """
        Apply an approved IFT submission and persist the updated state.

        This is the only method that may increment the monthly counter or
        write a transaction row.
        """
        decision = self.can_confirm(target_alloc)
        if not decision.allowed:
            return decision

        self.state["last_ift_date"] = self.today.isoformat()
        self.state["last_run_date"] = self.today.isoformat()

        if decision.is_safety_move:
            save_state(self.state)
            return decision

        self.state["ift_count_this_month"] = self.ift_count_this_month + 1
        try:
            append_transaction_row(self.today.isoformat(), current_alloc, target_alloc, regime)
        except Exception as e:
            # Persist state even if the audit log write fails.
            decision.reason += f" (warning: transaction log write failed: {e})"

        save_state(self.state)
        return decision
