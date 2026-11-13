"""
06_retrieval.py


Search a small robot manual using keyword overlap.
Return matching passages, their sources, and why they matched.

Uses only the python standard library.
"""

import re
from dataclasses import dataclass
from typing import List

@dataclass(frozen=True)
class Document:
    """
    A named document contain one or more paragraphs.
    """
    source: str
    text: str


@dataclass(frozen=True)
class Passage:
    """
    One searchable paragraph with a refreence to its sources.
    """
    source: str
    number: int
    text: str


@dataclass(frozen=True)
class SearchResult:
    """
    A matching passage and the query words found in it.
    """
    passage: Passage
    matched_words: tuple[str, ...]


def keywords(text: str) -> set[str]:
    """
    Extract distinct lowercase words, ignoring common filter words.

    :param text:
    :return:
    """
    stop_words = {
        "a", "an", "and",
        "do", "how", "i",
        "the", "to"
    }

    return set(re.findall(r"[a-z]+", text.lower())) - stop_words

class KeywordRetriever:

    def __init__(self, documents: List[Document]):
        """
        Prepare searchable passages from the supplied documents.

        :param documents:
        """
        self.passages: List[Passage] = []

        for document in documents:
            paragraph = [
                paragraph.strip() for paragraph in document.text.split("\n\n")
                if paragraph.strip()
            ]
            for number, paragraph in enumerate(paragraph, start=1):
                self.passages.append(
                    Passage(document.source, number, paragraph)
                )

    def search(self, query: str, limit: int = 2) -> List[SearchResult]:
        """
        Return up to 'limit' matches, strongest first.

        :param query:
        :param limit:
        :return:
        """
        if limit < 1:
            raise ValueError("'limit' must be greater than 0")

        query_words = keywords(query)
        results: List[SearchResult] = []
        for passage in self.passages:
            matched = query_words & keywords(passage.text)
            if matched:
                results.append(
                    SearchResult(passage, tuple(sorted(matched)))
                )
        results.sort(key=lambda result: len(result.matched_words), reverse=True)
        return results[:limit]


def main():
    """
    Show a successful search and a query with no matching passages.

    :return:
    """
    documents = [
        Document(
            source="Battery guide",
            text="""To recharge the battery, connect the robot to its charging dock.\n\n
            The battery holds enough power for two moves.
            """
        ),
        Document(
            source="Movement guide",
            text="Move one step towards the destination when the path is clear."
        ),
    ]

    retriever = KeywordRetriever(documents)
    for query in ("How do I recharge the battery?", "What is the warranty?"):
        print(f"\nQuestion: {query}")
        results: List[SearchResult] = retriever.search(query)

        if not results:
            print("No matching passages found.")
            continue

        for result in results:
            passage = result.passage
            print(f"{passage.source}, paragraph {passage.number}")
            print(f"  Matched words: {', '.join(result.matched_words)}")
            print(f"  {passage.text}")


if __name__ == "__main__":
    main()
