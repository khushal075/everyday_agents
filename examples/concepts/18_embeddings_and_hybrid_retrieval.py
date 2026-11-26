"""
18_embeddings_and_hybrid_retrieval.py

Search the robot's manual by meaning as well as by keywords, and combine the two.

Scenario:
    The same robot as examples 01-17: three moves from the destination,
    one battery unit, a battery that holds two. When the battery runs out
    or a move fails with an error code, the agent looks up the manual.

Goal:
    Find the right passage when the question uses different words from the manual,
    and still find exact terms such as error codes.

Difference from examples 06-08:
    Those examples matched shared words, so "refill its energy" could not find
    "recharge the battery". Here each passage is also turned into a vector, and
    passages with similar meaning have similar vectors.

Flow:
    1. Split the manual into passages and embed each one once (the index).
    2. For each question:
        - Keyword search scores passages by shared words.
        - Semantic search scores passages by cosine similarity of vectors.
        - Hybrid search merges both rankings with reciprocal rank fusion.
    3. Each search returns nothing when no passage is a good enough match.

New concepts:
    1. An embedding is a list of numbers that represents a text's meaning.
    2. Cosine similarity compares two vectors by direction, from -1 to 1.
    3. Passages are embedded once when the index is built; only the question
       is embedded per search.
    4. Keyword search misses paraphrases; semantic search can miss exact codes.
    5. Reciprocal rank fusion merges rankings by position, so scores on
       different scales never need to be compared.
    6. A minimum similarity keeps weak matches out of the results.

Modes:
    1. --toy                   A hand-made concept embedder (no model needed).
    2. --embed-model <name>    A local Ollama embedding model, e.g. nomic-embed-text.

The toy embedder is not a learned model. It maps words to a few hand-picked
concepts so the idea can be seen without downloading anything.

Requirements:
    Python's standard library. Model mode also needs a running Ollama server.
"""

import argparse
import json
import math
import re
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_QUESTIONS = (
    # Battery is at 0 with two steps left. A paraphrase: no shared words with the answer.
    "I'm out of energy. How do I refill it?",
    # The move tool returned an error code. Meaning alone does not help with codes.
    "What does E42 mean?",
    # Not covered by the manual: every search should return nothing.
    "Who built this robot?",
)

MANUAL = """
To recharge the battery, connect the robot to its charging dock.

A full battery holds two units, enough for two steps.

Each move uses one battery unit per step.

Error E42 means the move was blocked. Clear the path and try the move again.
"""

# "robot" appears throughout the manual, so it says nothing about which passage fits.
STOP_WORDS = {
    "a", "an", "and", "do", "does", "how", "i", "is", "it", "its", "m",
    "of", "robot", "the", "to", "what", "when",
}

# Hand-picked concepts for the toy embedder. Each word adds 1 to one concept.
CONCEPTS = {
    "energy": {"battery", "power", "energy"},
    "charging": {"recharge", "charge", "charging", "refill", "dock", "connect", "plug"},
    "motion": {"move", "moves", "step", "steps", "travel", "drive"},
    "fault": {"error", "blocked", "stuck", "fault", "jammed", "restart"},
    "route": {"destination", "path", "route"},
}


@dataclass(frozen=True)
class Passage:
    """
    One searchable paragraph of the manual, with an ID.
    """
    source: str
    text: str


@dataclass(frozen=True)
class ScoredPassage:
    """
    A passage and how well it matched one search.
    """
    passage: Passage
    score: float


class Embedder(Protocol):
    """
    Anything that turns texts into vectors of the same length.
    """

    def embed(self, texts: list[str]) -> list[list[float]]:
        ...


class Tokenizer:
    """
    Turn text into the words that searches compare.
    """

    def words(self, text: str) -> list[str]:
        """
        Extract lowercase words and codes, ignoring common filler words.

        :param text: Any text.
        :return: The remaining words, in order.
        """
        return [word for word in re.findall(r"[a-z0-9]+", text.lower()) if word not in STOP_WORDS]


class Manual:
    """
    The robot's manual, split into searchable passages.
    """

    def __init__(self, text: str) -> None:
        """
        Split the text into paragraphs and give each an ID.

        :param text: Paragraphs separated by blank lines.
        """
        paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
        self.passages = [
            Passage(source=f"manual-{number}", text=paragraph)
            for number, paragraph in enumerate(paragraphs, start=1)
        ]


class ToyConceptEmbedder:
    """
    Count how many words of each hand-picked concept a text contains.

    Words outside CONCEPTS, such as "E42", add nothing, so a text made only
    of them gets a zero vector.
    """

    def __init__(self, tokenizer: Tokenizer) -> None:
        """
        Store the tokenizer shared with keyword search.

        :param tokenizer: Splits text into words.
        """
        self.tokenizer = tokenizer

    def embed(self, texts: list[str]) -> list[list[float]]:
        """
        Return one vector per text, with one number per concept.

        :param texts: Texts to embed.
        :return: The vectors, in the same order.
        """
        vectors = []
        for text in texts:
            text_words = self.tokenizer.words(text)
            vectors.append([
                float(sum(word in members for word in text_words))
                for members in CONCEPTS.values()
            ])
        return vectors


class OllamaEmbedder:
    """
    Ask a local Ollama embedding model for vectors.
    """

    def __init__(self, model: str) -> None:
        """
        Store the installed embedding model name.

        :param model: An Ollama embedding model, e.g. nomic-embed-text.
        """
        self.model = model

    def embed(self, texts: list[str]) -> list[list[float]]:
        """
        Embed all texts in one request.

        :param texts: Texts to embed.
        :return: The vectors, in the same order.
        """
        request = Request(
            url="http://localhost:11434/api/embed",
            data=json.dumps({"model": self.model, "input": texts}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request, timeout=120) as response:
            vectors = json.load(response).get("embeddings")

        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise ValueError("The response did not contain one embedding per text.")
        return vectors


class KeywordRetriever:
    """
    Score passages by the share of the question's words they contain.
    """

    def __init__(self, passages: list[Passage], tokenizer: Tokenizer) -> None:
        """
        Store each passage's words once.

        :param passages:  The manual's passages.
        :param tokenizer: Splits text into words.
        """
        self.tokenizer = tokenizer
        self.index = [(passage, set(tokenizer.words(passage.text))) for passage in passages]

    def search(self, question: str, limit: int = 3) -> list[ScoredPassage]:
        """
        Return passages sharing at least one word, strongest first.

        :param question: The user's question.
        :param limit:    Maximum results.
        :return: Matches scored from 0 to 1.
        """
        question_words = set(self.tokenizer.words(question))
        if not question_words:
            return []

        results = []
        for passage, passage_words in self.index:
            shared = question_words & passage_words
            if shared:
                results.append(ScoredPassage(passage, len(shared) / len(question_words)))

        results.sort(key=lambda result: result.score, reverse=True)
        return results[:limit]


class SemanticRetriever:
    """
    Score passages by the cosine similarity of their vectors to the question's.
    """

    def __init__(self, passages: list[Passage], embedder: Embedder, min_similarity: float) -> None:
        """
        Embed every passage once to build the index.

        :param passages:       The manual's passages.
        :param embedder:       Turns texts into vectors.
        :param min_similarity: Results below this similarity are dropped.
        """
        self.embedder = embedder
        self.min_similarity = min_similarity
        vectors = embedder.embed([passage.text for passage in passages])
        self.index = list(zip(passages, vectors))

    @staticmethod
    def cosine(a: list[float], b: list[float]) -> float:
        """
        Compare two vectors by direction; length does not matter.

        :param a: A vector.
        :param b: A vector of the same length.
        :return: Similarity from -1 to 1, or 0 if either vector is all zeros.
        """
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return sum(x * y for x, y in zip(a, b)) / (norm_a * norm_b)

    def search(self, question: str, limit: int = 3) -> list[ScoredPassage]:
        """
        Embed the question and return the most similar passages.

        :param question: The user's question.
        :param limit:    Maximum results.
        :return: Matches at or above min_similarity, strongest first.
        """
        question_vector = self.embedder.embed([question])[0]
        results = [
            ScoredPassage(passage, self.cosine(question_vector, vector))
            for passage, vector in self.index
        ]
        results = [result for result in results if result.score >= self.min_similarity]
        results.sort(key=lambda result: result.score, reverse=True)
        return results[:limit]


class HybridRetriever:
    """
    Merge keyword and semantic rankings with reciprocal rank fusion.

    Each list adds 1 / (k + rank) for every passage it returns. Only positions
    are used, so a keyword score of 0.5 and a cosine of 0.5 are never compared.
    """

    def __init__(self, keyword: KeywordRetriever, semantic: SemanticRetriever, k: int = 60) -> None:
        """
        Store both retrievers and the fusion constant.

        :param keyword:  Finds exact words.
        :param semantic: Finds similar meaning.
        :param k:        Larger values give lower ranks relatively more weight.
        """
        self.keyword = keyword
        self.semantic = semantic
        self.k = k

    def search(self, question: str, limit: int = 3) -> list[ScoredPassage]:
        """
        Run both searches and combine their rankings.

        :param question: The user's question.
        :param limit:    Maximum results.
        :return: Fused results, strongest first.
        """
        fused: dict[str, float] = {}
        passages: dict[str, Passage] = {}

        for results in (self.keyword.search(question), self.semantic.search(question)):
            for rank, result in enumerate(results, start=1):
                source = result.passage.source
                fused[source] = fused.get(source, 0.0) + 1 / (self.k + rank)
                passages[source] = result.passage

        ranked = sorted(fused.items(), key=lambda item: item[1], reverse=True)
        return [ScoredPassage(passages[source], score) for source, score in ranked[:limit]]


class SearchComparison:
    """
    Run the same question through all three searches and print their top results.
    """

    def __init__(self, keyword: KeywordRetriever, semantic: SemanticRetriever, hybrid: HybridRetriever) -> None:
        """
        Store the three searches to compare.

        :param keyword:  Finds exact words.
        :param semantic: Finds similar meaning.
        :param hybrid:   Combines both.
        """
        self.searches = {"keyword": keyword, "semantic": semantic, "hybrid": hybrid}

    def compare(self, question: str) -> None:
        """
        Print each search's top result for one question.

        :param question: The user's question.
        :return: None.
        """
        print(f"\nQuestion: {question}")
        for label, search in self.searches.items():
            results = search.search(question)
            if not results:
                print(f"  {label:<8} no match")
                continue
            top = results[0]
            print(f"  {label:<8} {top.passage.source} ({top.score:.3f}): {top.passage.text}")


def main() -> None:
    """
    Compare keyword, semantic and hybrid search on questions that each one finds hard.

    :return: None.
    """
    parser = argparse.ArgumentParser(description="Compare keyword, semantic and hybrid search.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--toy", action="store_true", help="Use the hand-made concept embedder.")
    mode.add_argument("--embed-model", help="An installed Ollama embedding model.")
    parser.add_argument("--min-similarity", type=float, default=None,
                        help="Drop semantic matches below this (default: 0.5 toy, 0.6 model).")
    parser.add_argument("questions", nargs="*", help="Questions to search for.")
    args = parser.parse_args()

    tokenizer = Tokenizer()
    embedder: Embedder = (
        OllamaEmbedder(args.embed_model) if args.embed_model else ToyConceptEmbedder(tokenizer)
    )
    # Similarity scales differ between embedders, so each needs its own threshold.
    min_similarity = args.min_similarity if args.min_similarity is not None else (
        0.6 if args.embed_model else 0.5
    )

    passages = Manual(MANUAL).passages
    print("Robot: distance 3, battery 1 of 2 units.")
    try:
        keyword = KeywordRetriever(passages, tokenizer)
        semantic = SemanticRetriever(passages, embedder, min_similarity)
        comparison = SearchComparison(keyword, semantic, HybridRetriever(keyword, semantic))

        for question in args.questions or DEFAULT_QUESTIONS:
            comparison.compare(question)
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        parser.exit(1, f"Ollama HTTP {error.code}: {detail}\n")
    except (URLError, TimeoutError, ValueError) as error:
        parser.exit(1, f"Could not run the embedding model: {error}\n")


if __name__ == "__main__":
    # Example commands:
    #   uv run python 18_embeddings_and_hybrid_retrieval.py --toy
    #   uv run python 18_embeddings_and_hybrid_retrieval.py --toy "The move was blocked"
    #   ollama pull nomic-embed-text
    #   uv run python 18_embeddings_and_hybrid_retrieval.py --embed-model nomic-embed-text
    main()
