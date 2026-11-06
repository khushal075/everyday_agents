"""Command-line entry point for the sentiment-focused v0.1 release."""

import argparse
from collections.abc import Sequence
from dataclasses import asdict
from importlib.metadata import version
import json
from pathlib import Path
from pickle import UnpicklingError
from typing import Any


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="everyday-agents", description="Small models and practical agents")
    parser.add_argument("--version", action="version", version=f"%(prog)s {version('everyday-agents')}")
    agents = parser.add_subparsers(dest="agent", required=True)
    sentiment = agents.add_parser("sentiment", help="Classify, route, train, and evaluate sentiment")
    commands = sentiment.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="Run one complete agent cycle")
    run.add_argument("--text", required=True)
    run.add_argument("--model", type=Path, help="Trusted saved model directory; defaults to rules baseline")

    train = commands.add_parser("train", help="Train, compare on validation, and save a new artifact")
    train.add_argument("--data", type=Path, required=True, help="Labelled CSV or JSONL dataset")
    train.add_argument("--output", type=Path, required=True, help="New model directory; never overwritten")
    train.add_argument("--seed", type=int, default=42)
    train.add_argument("--model-version", default="1.0.0")
    train.add_argument("--evaluate-test", action="store_true", help="Include final test report after choices are fixed")

    evaluate = commands.add_parser("evaluate", help="Compare a saved model with baseline on independent labelled data")
    evaluate.add_argument("--model", type=Path, required=True, help="Trusted saved model directory")
    evaluate.add_argument("--data", type=Path, required=True, help="Independent held-out CSV or JSONL; never fitted")
    return parser


def _dispatch(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "run":
        from .agents.sentiment import create_agent
        if args.model is None:
            return asdict(create_agent().run(args.text))
        from .agents.sentiment.predictor import load_predictor
        loaded = load_predictor(args.model)
        return asdict(create_agent(predictor=loaded.model).run(args.text))

    if args.command == "train":
        from .agents.sentiment.train import training_report
        return training_report(
            args.data, seed=args.seed, output=args.output,
            model_version=args.model_version, evaluate_test=args.evaluate_test,
        )

    from .agents.sentiment.evaluation import compare_with_baseline
    from .agents.sentiment.predictor import load_predictor
    from .agents.sentiment.train import load_examples
    loaded = load_predictor(args.model)
    return {
        "model": asdict(loaded.metadata),
        "evaluation": asdict(compare_with_baseline(loaded.model, load_examples(args.data))),
    }


def main(argv: Sequence[str] | None = None) -> None:
    """Print one JSON object on success; argparse errors go to stderr."""
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        output = _dispatch(args)
        payload = json.dumps(output, indent=2, ensure_ascii=False, allow_nan=False)
    except (OSError, ValueError, TypeError, EOFError, UnpicklingError, ImportError) as exc:
        parser.error(str(exc))
    print(payload)


if __name__ == "__main__":
    main()
