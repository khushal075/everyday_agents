"""Run the local rules-based agent and print completed runs as JSON.

Usage:
    uv run python examples/sentiment_demo.py
    uv run python examples/sentiment_demo.py --text "This is terrible"
"""

import argparse
from collections.abc import Sequence
from dataclasses import asdict
import json

from everyday_agents.agents.sentiment import create_agent


_DEFAULT_TEXTS = (
    "I love this helpful product",
    "This is terrible and broken",
    "Delivery arrived today",
)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Local sentiment agent using a rules baseline")
    parser.add_argument("--text", action="append", help="Feedback to process; repeat for multiple items")
    args = parser.parse_args(argv)
    agent = create_agent()
    try:
        runs = [asdict(agent.run(text)) for text in (args.text or _DEFAULT_TEXTS)]
    except (TypeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(runs, indent=2, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
