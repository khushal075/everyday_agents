"""Local feedback actions with verifiable, in-memory records."""

from dataclasses import asdict
from typing import Literal
from uuid import uuid4

from everyday_agents.core.schemas import ActionResult, Decision

from .schemas import FeedbackRecord


class FeedbackTool:
    """Handle record/prepare_review without external systems or persistence.

    Each execution creates a new record, including repeated identical feedback.
    Records last only as long as this tool instance. This is not a database or
    a production review queue. Unsupported actions and parameters fail before
    any record is created.
    """

    def __init__(self) -> None:
        self._records: dict[str, FeedbackRecord] = {}

    @property
    def records(self) -> tuple[FeedbackRecord, ...]:
        """Return an insertion-ordered snapshot of the immutable records."""
        return tuple(self._records.values())

    def execute(self, input_data: str, decision: Decision) -> ActionResult:
        if not isinstance(input_data, str):
            raise TypeError("Feedback input must be a string")
        if not input_data.strip():
            raise ValueError("Feedback input must not be empty")
        if decision.action not in {"record", "prepare_review"}:
            raise ValueError(f"Unsupported feedback action: {decision.action!r}")
        if decision.parameters:
            raise ValueError("Feedback actions do not accept parameters")

        status: Literal["recorded", "pending_review"] = (
            "recorded" if decision.action == "record" else "pending_review"
        )
        record = FeedbackRecord(
            record_id=uuid4().hex,
            text=input_data,
            status=status,
            reason=decision.reason,
        )
        self._records[record.record_id] = record
        return ActionResult(success=True, details=asdict(record))

    def verify(self, result: ActionResult) -> bool:
        """Confirm that all reported fields match this instance's stored record."""
        if not result.success:
            return False
        record_id = result.details.get("record_id")
        if not isinstance(record_id, str):
            return False
        record = self._records.get(record_id)
        return record is not None and result.details == asdict(record)
