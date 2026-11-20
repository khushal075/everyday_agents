"""
    - Load fixed sentiment workflow cases from a JSON file.
    - Compare observed predictions, actions, and tool statuses expectations.
    - Emit one structured event for each case.
    - Exit with non-zero code when a case fails or the fixture is invalid.
"""

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from everyday_agents.agents.sentiment.agent import create_agent
from production.category_04_evaluation_and_observability.telemetry import EventOutcome, Telemetry


DEFAULT_CASES = (Path(__file__).resolve().parent / "fixtures" / "evaluation_cases.jsonl")


class EvalutionCase(BaseModel):
    """
        - Define the input and expected outputs for one baseline workflow case.
        - Reject unknown fixture fields and unsupported expectation values.
    """
    model_config = ConfigDict(extra="forbid", strict=True)
    case_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    expected_sentiment: Literal["positive", "negative", "uncertain"]
    expected_action: Literal["record", "prepare_review"]
    expected_status: Literal["recorded", "pending_review"]


@dataclass(frozen=True)
class EvaluationResult:
    """
        - Store the observed outcome of one evaluation case.
        - Keep mismatch descriptions for human-readable report.
    """
    case_id: str
    outcome: EventOutcome
    details: tuple[str, ...]


def load_cases(path: Path) -> list[EvalutionCase]:
    """
        - Parse non empty JSONL lines into validated evaluation cases.
        - Reject duplicate case IDs and empty fixtures.
        - Include the filename and line number when a case is invalid.
    """
    cases: list[EvalutionCase] = []
    seen_ids: set[str] = set()

    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            case = EvalutionCase.model_validate(json.loads(line))
        except (json.JSONDecodeError, ValidationError) as error:
            raise ValueError(
                f"{path}, line {line_number}: {error}"
            )  from error

        if not case.case_id.strip() or not case.text.strip():
            raise ValueError(
                f"{path}, line {line_number}: Case Id and text must contain words."
            )
        if case.case_id in seen_ids:
            raise ValueError(
                f"{path}, line {line_number}: duplicate case ID {case.case_id!r}."
            )

        seen_ids.add(case.case_id)
        cases.append(case)

    if not cases:
        raise ValueError(f"No Evaluation cases found in {path}")

    return cases

class WorkflowEvaluator:
    """
        - Run cases through the existing sentiment agent.
        - Create a fresh agent for each case to isolate local tool records.
        - Associate all case events with one evaluation run ID.
    """
    def __init__(self, telemetry: Telemetry) -> None:
        """
            - Store the event emitter.
            - Assign an identifier to this evaluation run.
        """
        self.telemetry = telemetry
        self.run_id = uuid4().hex

    def evaluate(self, case: EvalutionCase) -> EvaluationResult:
        """
            - Execute one prediction, decision, action and verification cycle.
            - Compare its outputs with the case expectations.
            - Record exceptions are error outcomes and emit the timing event.
        """
        started = perf_counter()
        details: list[str] = []
        outcome: EventOutcome = "passed"
        error_type: Optional[str] = None
        try:
            run = create_agent().run(case.text)
            checks = (
                ("sentiment", case.expected_sentiment, run.prediction.sentiment),
                ("action", case.expected_action, run.decision.action),
                ("tool status", case.expected_status, run.result.details.get('status')),
                ("tool success", True, run.result.success),
            )
            for name, expected, observed in checks:
                if observed != expected:
                    details.append(f"{name}: expected {expected!r}, got {observed!r}")

            if details:
                outcome = "failed"
        except Exception as error:
            outcome = "error"
            error_type = type(error).__name__
            details.append(f"{error_type}: {error}")

        self.telemetry.emit(
            run_id=self.run_id,
            stage=f"evaluation.{case.case_id}",
            outcome=outcome,
            duration_ms=(perf_counter() - started) * 1_000,
            error_type=error_type
        )

        return EvaluationResult(case.case_id, outcome, details=tuple(details))


def main():
    """
        - Accept an optional fixture part from the command line.
        - Print each result and the total number of passing cases.
        - return 0 for passing run, 1 for failing and 2 for invalid input.
    """
    parser = argparse.ArgumentParser(description="Evaluate the sentiment baseline workflow")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    args = parser.parse_args()

    try:
        cases = load_cases(args.cases)
    except (OSError, ValueError) as error:
        print(f"Evaluation input error: {error}")
        return 2

    evaluator = WorkflowEvaluator(telemetry=Telemetry())
    results = [evaluator.evaluate(case) for case in cases]

    for result in results:
        print(f"{result.outcome.upper()} | {result.case_id}")
        for detail in result.details:
            print(f"  {detail}")

    passed = sum(result.outcome == "passed" for result in results)
    print(f"\nSummary: {passed} / {len(results)} passed")
    return 0 if passed == len(results) else 1

if __name__ == "__main__":
    raise SystemExit(main())
