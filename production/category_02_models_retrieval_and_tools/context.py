"""
Prepare feedback and supporting policy passage for the model request.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from production.category_02_models_retrieval_and_tools.retrieval import PolicyPassage, PolicyMatch


@dataclass(frozen=True)
class ModelContext:
    """
    The original feedback and the policy evidence selected for it.
    """
    feedback: str
    evidence: tuple[PolicyPassage, ...]


class ContextBuilder:
    """
    Select ranked policy passage within a size limit.
    """

    def __init__(
            self,
            max_passages: int = 2,
            max_evidence_chars: int = 1_500,
    ):
        if max_passages < 1 or max_evidence_chars < 1:
            raise ValueError("Context limit must be positive.")

        self.max_passages = max_passages
        self.max_evidence_chars = max_evidence_chars

    def build(
            self,
            feedback: str,
            matches: Sequence[PolicyMatch],
    ) -> ModelContext:
        """
        Keep the highest ranked complete passage that fit the budget.
        """
        evidence: list[PolicyPassage] = []
        remaining_chars = self.max_evidence_chars

        for match in matches:
            if len(evidence) == self.max_passages:
                break
            passage = match.passage
            passage_chars = len(passage.source) + len(passage.heading) + len(passage.text)

            if passage_chars > remaining_chars:
                continue

            evidence.append(passage)
            remaining_chars -= passage_chars

        return ModelContext(feedback=feedback, evidence=tuple(evidence))
