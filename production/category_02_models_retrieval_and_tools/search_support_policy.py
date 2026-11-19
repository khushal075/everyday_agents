"""
Demonstrate a policy match and a request with no matching evidence.
"""

from pathlib import Path
from production.category_02_models_retrieval_and_tools.retrieval import PolicyRetriever

POLICY_PATH = Path(__file__).resolve().parent / "fixtures" / "support_policy.md"

def main():
    """
    Search the same policy for two different feedback message.
    """
    retriever = PolicyRetriever(POLICY_PATH)
    requests = (
        "I was charged twice for my subscription.",
        "Can you add dark mode?",
    )

    for request in requests:
        print(f"\nFeedback: {request}")
        matches = retriever.search(request)
        if not matches:
            print("No matching policy passage found.")
            continue

        for match in matches:
            passage = match.passage
            print(f"Policy: {passage.heading}")
            print(f"Source: {passage.source}")
            print(f"Matched words: {', '.join(match.matched_words)}")
            print(passage.text)


if __name__ == "__main__":
    # uv run python -m production.category_02_models_retrieval_and_tools.search_support_policy
    main()
