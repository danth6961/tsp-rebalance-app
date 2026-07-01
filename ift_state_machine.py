"""
ift_state_machine.py — The single enforced writer for IFT-related state.

Owns: eligibility checks and the ONLY code path that may mutate
ift_count_this_month, last_ift_date, last_run_date, or write a
transaction audit row.

Should NOT contain: scoring logic, regime selection, Streamlit widgets,
or config I/O beyond what's needed to read/write AppState.

Why this module exists: previously (see module_weakness_review.md §1B)
app.py had two independent places that reasoned about IFT eligibility --
the sidebar button's `disabled=` check (only looked at engine_ran) and
confirm_ift_used()'s internal monthly-cap check -- with no code-level
guarantee they'd stay in agreement. Wrapping both in one class means
there is exactly one function (`confirm`) that can change IFT state, and
exactly one function (`can_confirm`) that decides whether it's allowed.
"""
from dataclasses import dataclass
from datetime import date
from typing import Dict, Optional

from storage import load_state_for_today, save_state, append_transaction_row

# Tolerance for float-rounding drift in engine.py's normalize-to-100
# allocation math (round(v / total * 100, 1) can yield 99.9/100.1 instead
# of an exact 100.0/0.0 for an intended pure-G move).
G_MOVE_TOLERANCE_PCT = 0.5

MONTHLY_IFT_LIMIT = 2


def is_pure_g_move(target_alloc: Dict[str, float]) -> bool:
    """True if the target allocation is effectively 100% G Fund.

    Uses a tolerance band instead of exact float equality to absorb
    normalization rounding drift from engine.py's allocation math.
    """
    g = float(target_alloc.get("G", 0.0))
    others = sum(float(target_alloc.get(f, 0.0)) for f in ("C", "I", "S", "F"))
    return abs(g - 100.0) <= G_MOVE_TOLERANCE_PCT and others <= G_MOVE_TOLERANCE_PCT


@dataclass
class IFTDecision:
    """Result of an eligibility check. `allowed=False` always carries a
    human-readable `reason` so the UI never has to guess why a button
    is disabled."""
    allowed: bool
    reason: str
    is_safety_move: bool = False


class IFTStateMachine:
    """
    Wraps AppState and enforces that IFT count / transaction history can
    only change through `confirm()`.

    Usage:
        machine = IFTStateMachine.load(today)
        decision = machine.can_confirm(target_alloc)
        if decision.allowed:
            machine.confirm(current_alloc, target_alloc, regime)
    """

    def __init__(self, state: Dict, today: date):
        # Rollover is applied on every load, so eligibility checks never
        # operate on a stale prior month's counter.
        self.state = state
        self.today = today

    @classmethod
    def load(cls, today: date) -> "IFTStateMachine":
        """Construct from disk, applying month rollover."""
        return cls(load_state_for_today(today), today)

    @property
    def ift_count_this_month(self) -> int:
        return int(self.state.get("ift_count_this_month", 0))

    @property
    def last_ift_date(self) -> Optional[date]:
        raw = self.state.get("last_ift_date")
        return date.fromisoformat(raw) if raw else None

    def can_confirm(self, target_alloc: Dict[str, float]) -> IFTDecision:
        """Determine whether a manual IFT confirmation should be allowed
        right now, without mutating any state.

        A pure G-Fund safety move is always allowed and never blocked by
        the monthly cap, matching the TSP rule that G-only safety moves
        don't consume a normal Interfund Transfer.
        """
        if is_pure_g_move(target_alloc):
            return IFTDecision(allowed=True, reason="G Fund safety move (does not count toward monthly cap)", is_safety_move=True)

        if self.ift_count_this_month >= MONTHLY_IFT_LIMIT:
            return IFTDecision(allowed=False, reason=f"Monthly IFT limit of {MONTHLY_IFT_LIMIT} already reached")

        return IFTDecision(allowed=True, reason="Within monthly IFT allowance")

    def confirm(self, current_alloc: Dict[str, float], target_alloc: Dict[str, float], regime: str) -> IFTDecision:
        """
        The ONLY method in the codebase that may increment
        ift_count_this_month, set last_ift_date, or append a transaction
        row. Re-validates eligibility internally so callers cannot bypass
        can_confirm() by calling confirm() directly.
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
            # Persist the state change even if the audit-log write fails --
            # losing a log row is recoverable; silently under-counting a
            # real IFT the user believes they've submitted is not.
            decision.reason += f" (warning: transaction log write failed: {e})"

        save_state(self.state)
        return decision
