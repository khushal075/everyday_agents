"""
Search Markdown policy sections by keyword overlap.
"""

import re
from dataclasses import dataclass
from pathlib import Path

SECTION_HEADING = re.compile(r"^##[ \t]+(.+)$", re.MULTILINE)
WORD = re.compile(r"[^\W\d_]+")

STOP_WORDS = frozenset(
    "a an and are can do for how i in is it me my of on or "
    "that the this to was were what when with you your".split()
)

def keywords(text: str) -> set[str]:
    return set(WORD.findall(text.casefold())) - STOP_WORDS

@dataclass(frozen=True)
class PolicyPassage:
    """
    The Policy section with its source file and heading.
    """
    source: str
    heading: str
    text: str


@dataclass(frozen=True)
class PolicyMatch:
    """
    A passage and the words it shares with the query.
    """
    passage: PolicyPassage
    matched_words: tuple[str, ...]


class PolicyRetriever:
    """
    Load a sample policy and rank its sections by keyword overlap.
    """
    def __init__(self, policy_path: Path):
        sections = SECTION_HEADING.split(policy_path.read_text(encoding="utf-8"))

        # The first element is the introduction. The rest alternate between
        # Sections headings and section bodies.

        self.passage = [
            PolicyPassage(
                source=policy_path.name,
                heading=heading.strip(),
                text=body.strip(),
            )
            for heading, body in zip(sections[1::2], sections[2::2], strict=True)
            if body.strip()
        ]

        if not self.passage:
            raise ValueError(f"No Policy section found in {policy_path}")

    def search(
            self,
            query: str,
            limit: int = 2
    ) -> list[PolicyMatch]:
        """
        Return the strongest matches, keeping document order for ties.
        """
        if limit < 1:
            raise ValueError("Limit must be >= 1")

        query_words =  keywords(query)
        matches: list[PolicyMatch] = []

        for passage in self.passage:
            matched_words = query_words & keywords(passage.text)
            if matched_words:
                matches.append(PolicyMatch(passage, tuple(sorted(matched_words))))

        matches.sort(key=lambda match: len(match.matched_words), reverse=True)
        return matches[:limit]
