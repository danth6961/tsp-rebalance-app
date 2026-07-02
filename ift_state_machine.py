"""
ift_state_machine.py — Single-writer IFT state management.

Owns:
- IFT eligibility checks
- Monthly cap enforcement and idempotency confirmation
- Persistent audit logging for state mutations

Note:
This module intentionally does not own scoring logic, UI rendering, or data fetching.
"""

from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from typing import Optional, Dict

from storage import append_transaction_row, load_state_for_today, save_state
from constants import G_MOVE_TOLERANCE_PCT, MONTHLY_IFT_LIMIT
import logging

# Configure module-level logging for audit purposes.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def is_pure_g_move(target_alloc: Dict[str, float]) -> bool:
    """
    Determine if the target allocation is a pure G Fund move.
    
    A pure G move means the G Fund is very close to 100% (allowing for a small tolerance) and all other funds are near 0.
    
    Parameters
    ----------
    target_alloc : Dict[str, float]
        Mapping of fund names to allocation percentages.
    
    Returns
    -------
    bool
        True if the allocation qualifies as a pure G move, else False.
    """
    g = float(target_alloc.get("G", 0.0))
    others = sum(float(target_alloc.get(fund, 0.0)) for fund in ("C", "I", "S", "F"))
    return abs(g - 100.0) <= G_MOVE_TOLERANCE_PCT and others <= G_MOVE_TOLERANCE_PCT


@dataclass(frozen=True)
class IFTDecision:
    """
    Container for IFT eligibility and confirmation results.
    
    Attributes:
        allowed (bool): True if an IFT is permitted.
        reason (str): Explanation for the decision.
        is_safety_move (bool): True if the move is a safety move (pure G fund move).
        transaction_written (bool): True if the transaction log was successfully written.
        state_saved (bool): True if state update was saved to storage.
    """
    allowed: bool
    reason: str
    is_safety_move: bool = False
    transaction_written: bool = False
    state_saved: bool = False


class IFTStateMachine:
    """
    Manages IFT state transitions ensuring that any state mutations (transaction logging and state persistence)
    occur only through validated pathways.

    Attributes:
        state (Dict[str, object]): The current persistent state.
        today (date): The current business date.
    """

    def __init__(self, state: Dict[str, object], today: date) -> None:
        self.state: Dict[str, object] = state
        self.today: date = today

    @classmethod
    def load(cls, today: date) -> IFTStateMachine:
        """
        Load persistent state from disk with month rollover applied.
        
        Parameters
        ----------
        today : date
            Current date to be used for rollover.
        
        Returns
        -------
        IFTStateMachine
            An instance with current state data.
        """
        return cls(load_state_for_today(today), today)

    @property
    def ift_count_this_month(self) -> int:
        """
        Retrieve the count of IFT confirmations used in the current month.
        
        Returns
        -------
        int
            Monthly IFT count.
        """
        return int(self.state.get("ift_count_this_month", 0))

    @property
    def last_ift_date(self) -> Optional[date]:
        """
        Retrieve the most recent IFT confirmation date.
        
        Returns
        -------
        Optional[date]
            Date if available, otherwise None.
        """
        raw = self.state.get("last_ift_date")
        if not raw:
            return None
        return date.fromisoformat(str(raw))

    def can_confirm(self, target_alloc: Dict[str, float]) -> IFTDecision:
        """
        Check if a manual IFT confirmation is permitted based on the target allocation and monthly cap.
        
        Parameters
        ----------
        target_alloc : Dict[str, float]
            Proposed fund allocation for the IFT.
        
        Returns
        -------
        IFTDecision
            Preliminary decision without performing state mutation.
        """
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
        current_alloc: Dict[str, float],
        target_alloc: Dict[str, float],
        regime: str,
        confirmation_key: Optional[str] = None,
    ) -> IFTDecision:
        """
        Confirm an IFT submission after ensuring that it is valid.
        
        Performs idempotency checks, updates state timestamps, logs the transaction, and persists state.
        
        Parameters
        ----------
        current_alloc : Dict[str, float]
            Current allocation before IFT.
        target_alloc : Dict[str, float]
            Proposed allocation for IFT.
        regime : str
            Regime name associated with the move.
        confirmation_key : Optional[str], optional
            Key to ensure idempotent operations, by default None.
        
        Returns
        -------
        IFTDecision
            Outcome of the confirmation action including persistence flags.
        """
        # Idempotency check: prevent duplicate confirmations.
        if confirmation_key is not None:
            last_key = str(self.state.get("last_confirmation_key", ""))
            if last_key == confirmation_key:
                logger.info("Duplicate confirmation ignored.")
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

        # Update state timestamps (recording even safety moves).
        self.state["last_ift_date"] = self.today.isoformat()
        self.state["last_run_date"] = self.today.isoformat()

        if confirmation_key is not None:
            self.state["last_confirmation_key"] = confirmation_key

        # Handle safety moves: these do not consume the monthly allowance.
        if decision.is_safety_move:
            try:
                save_state(self.state)
                logger.info("Safety move recorded without consuming IFT count.")
                return IFTDecision(
                    allowed=True,
                    reason=decision.reason,
                    is_safety_move=True,
                    transaction_written=False,
                    state_saved=True,
                )
            except Exception as e:
                logger.error("Failed to save state for safety move: %s", e)
                return IFTDecision(
                    allowed=False,
                    reason="Failed to persist state for safety move",
                    is_safety_move=True,
                )

        # Process a normal IFT submission.
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
            logger.info("Transaction row successfully appended.")
        except Exception as exc:
            logger.error("Transaction log append failed: %s", exc)
            # We record the failure in the decision without aborting state update.
            decision = IFTDecision(
                allowed=True,
                reason=f"Within monthly IFT allowance (warning: transaction log write failed: {exc})",
                is_safety_move=False,
                transaction_written=False,
                state_saved=False,
            )

        try:
            save_state(self.state)
            state_saved = True
            logger.info("State successfully saved after IFT confirmation.")
        except Exception as e:
            logger.error("Failed to persist state after IFT confirmation: %s", e)
            state_saved = False

        return IFTDecision(
            allowed=True,
            reason=decision.reason,
            is_safety_move=False,
            transaction_written=transaction_written,
            state_saved=state_saved,
        )
