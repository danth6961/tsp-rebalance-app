"""
ift_state_machine.py — single-writer IFT state management.

Owns:
- IFT eligibility checks
- monthly cap enforcement
- idempotent confirmation handling
- the only code path that may mutate IFT counters
- transaction audit writes

Does not own:
- scoring
- regime selection
- UI rendering
- data fetching
- config file I/O
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable

from storage import append_transaction_row, load_state_for_today, save_state

# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------
# A tolerance is needed because engine.py normalizes allocations to 100.0 with
# rounding, which can leave tiny decimal residue between rows.
# -----------------------------------------------------------------------------
G_MOVE_TOLERANCE_PCT: float = 0.5
MONTHLY_IFT_LIMIT: int = 2


# -----------------------------------------------------------------------------
# Pure helper
# -----------------------------------------------------------------------------
# This helper determines whether the target allocation is effectively a pure
# G Fund move. Pure G safety moves do not consume monthly IFT capacity.
# -----------------------------------------------------------------------------


def is_pure_g_move(target_alloc: dict[str, float]) -> bool:
    """Return True if the target allocation is effectively 100% G Fund."""
    g = float(target_alloc.get("G", 0.0))
    others = sum(float(target_alloc.get(fund, 0.0)) for fund in ("C", "I", "S", "F"))
    return abs(g - 100.0) <= G_MOVE_TOLERANCE_PCT and others <= G_MOVE_TOLERANCE_PCT


# -----------------------------------------------------------------------------
# Decision contract
# -----------------------------------------------------------------------------
# This is returned by eligibility checks and confirmations so the UI can show
# a clear reason and downstream code can tell whether the move was a safety move.
# -----------------------------------------------------------------------------
@dataclass(frozen=True)
class IFTDecision:
    """Result of an IFT eligibility check or confirmation attempt."""

    allowed: bool
    reason: str
    is_safety_move: bool = False
    transaction_written: bool = False
    state_saved: bool = False


# -----------------------------------------------------------------------------
# State machine
# -----------------------------------------------------------------------------
# This class is intentionally the only place allowed to mutate IFT counters.
# It relies on storage.py for persistence, but keeps the mutation workflow here.
# -----------------------------------------------------------------------------
class IFTStateMachine:
    """Enforce that IFT state changes only happen through confirm()."""

    def __init__(self, state: dict[str, object], today: date) -> None:
        # Load-time month rollover is applied by storage.load_state_for_today().
        self.state: dict[str, object] = state
        self.today: date = today

    @classmethod
    def load(cls, today: date) -> "IFTStateMachine":
        """Load state from disk with month rollover applied."""
        return cls(load_state_for_today(today), today)

    @property
    def ift_count_this_month(self) -> int:
        """Return the current month's confirmed IFT count."""
        return int(self.state.get("ift_count_this_month", 0))

    @property
    def last_ift_date(self) -> date | None:
        """Return the most recent IFT date, if present."""
        raw = self.state.get("last_ift_date")
        if not raw:
            return None
        return date.fromisoformat(str(raw))

    def can_confirm(self, target_alloc: dict[str, float]) -> IFTDecision:
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

    def confirm(
        self,
        current_alloc: dict[str, float],
        target_alloc: dict[str, float],
        regime: str,
        confirmation_key: str | None = None,
    ) -> IFTDecision:
        """Apply an approved IFT submission and persist the updated state.

        Parameters
        ----------
        current_alloc:
            Current fund allocation before the move.
        target_alloc:
            Target allocation to confirm.
        regime:
            Regime name used for audit logging.
        confirmation_key:
            Optional idempotency key to prevent double confirmation on reruns.

        Returns
        -------
        IFTDecision
            Decision result including persistence flags.
        """
        # Idempotency guard: repeated reruns / duplicate clicks should not
        # double-count or duplicate audit rows.
        if confirmation_key is not None:
            last_key = str(self.state.get("last_confirmation_key", ""))
            if last_key == confirmation_key:
                return IFTDecision(
                    allowed=True,
                    reason="Duplicate confirmation ignored",
                    is_safety_move=is_pure_g_move(target_alloc),
                    transaction_written=False,
                    state_saved=False,
                )

        decision = self.can_confirm(target_alloc)
        if not decision.allowed:
            return decision

        # Update state timestamps first so even safety moves are recorded.
        self.state["last_ift_date"] = self.today.isoformat()
        self.state["last_run_date"] = self.today.isoformat()

        # Track the idempotency key if provided.
        if confirmation_key is not None:
            self.state["last_confirmation_key"] = confirmation_key

        # Safety moves do not consume IFT capacity.
        if decision.is_safety_move:
            save_state(self.state)
            return IFTDecision(
                allowed=True,
                reason=decision.reason,
                is_safety_move=True,
                transaction_written=False,
                state_saved=True,
            )

        # Normal IFT submission consumes monthly allowance.
        self.state["ift_count_this_month"] = self.ift_count_this_month + 1

        transaction_written = False
        try:
            append_transaction_row(
                self.today.isoformat(),
                current_alloc,
                target_alloc,
                regime,
            )
            transaction_written = True
        except Exception as exc:
            # Persist state even if the audit row fails, but preserve the warning.
            decision = IFTDecision(
                allowed=True,
                reason=f"Within monthly IFT allowance (warning: transaction log write failed: {exc})",
                is_safety_move=False,
                transaction_written=False,
                state_saved=False,
            )

        save_state(self.state)

        return IFTDecision(
            allowed=True,
            reason=decision.reason,
            is_safety_move=False,
            transaction_written=transaction_written,
            state_saved=True,
        )


__all__ = [
    "G_MOVE_TOLERANCE_PCT",
    "MONTHLY_IFT_LIMIT",
    "is_pure_g_move",
    "IFTDecision",
    "IFTStateMachine",
]
