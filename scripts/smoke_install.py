"""Verify an installed package from outside the source tree.

Usage: python scripts/smoke_install.py --python /path/to/clean/venv/bin/python
The caller installs the built wheel into that environment first.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", type=Path, required=True)
    args = parser.parse_args()
    interpreter = args.python.absolute()
    sample = Path(__file__).resolve().parents[1] / "data/samples/sentiment/feedback.jsonl"
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    with tempfile.TemporaryDirectory() as directory:
        def run(*arguments):
            return subprocess.run(
                [str(interpreter), "-m", "everyday_agents", *arguments],
                cwd=directory, env=environment, capture_output=True, text=True, check=True,
            ).stdout
        assert run("--version").strip() == "everyday-agents 0.1.0"
        baseline = json.loads(run("sentiment", "run", "--text", "terrible"))
        assert baseline["result"]["success"]
        model = str(Path(directory) / "model")
        trained = json.loads(run("sentiment", "train", "--data", str(sample), "--output", model))
        assert "validation" in trained and "test" not in trained
        loaded = json.loads(run("sentiment", "run", "--model", model, "--text", "helpful service"))
        assert loaded["result"]["success"]
        assert set(loaded["prediction"]["probabilities"]) == {"positive", "negative", "neutral"}
    print("Clean installed-package smoke check passed: version, baseline, training, save/load, agent run.")


if __name__ == "__main__":
    main()
