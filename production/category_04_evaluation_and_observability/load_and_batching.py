"""
    - Compare individual, concurrent, and batched model inference.
    - Train the existing sentiment pipeline outside the measured intervals.
    - Verify that each execution mode produces equivalent probabilities.
    - Report model throughput separately from API and worker performance.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

import numpy as np
from sklearn.pipeline import Pipeline
from everyday_agents.agents.sentiment.train import train_from_file

TRAINING_DATA = (
    Path(__file__).resolve().parents[2] / "data/samples/sentiment/feedback.jsonl"
)


@dataclass(frozen=True)
class BenchmarkResult:
    """
        - Describe one measured inference mode.
        - Record total elapsed time and the number of processed texts.
    """
    mode: str
    text_count: int
    elapsed_seconds: float


class InferenceBenchmark:
    """
        - Measure inference using the same fitted pipeline and input order.
        - Check probabilities against a reference result before reporting.
    """

    def __init__(self, pipeline: Pipeline, texts: list[str]) -> None:
        """
            - Store the fitted model and benchmark inputs.
            - Prepare reference probabilities and warm the model.
        """
        self.pipeline = pipeline
        self.texts = texts
        self.reference = pipeline.predict_proba(self.texts)

    def predict_one(self, text: str) -> np.ndarray:
        """
            - Run one text through the fitted pipeline.
            - Return its class probabilities.
        """
        return self.pipeline.predict_proba([text])[0]

    def run(self, batch_size: int, workers: int) -> BenchmarkResult:
        """
            - Run concurrent individual inference or sequential batch inference.
            - Include executor setup in the concurrent measurement.
            - Verify that all outputs match the reference probabilities.
        """
        started = perf_counter()

        if workers > 1:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                probabilities = np.asarray(
                    list(executor.map(self.predict_one, self.texts))
                )
            mode = f"Individual, workers={workers}"
        else:
            batches = [
                self.pipeline.predict_proba(
                    self.texts[start: start + batch_size]
                )
                for start in range(0, len(self.texts), batch_size)
            ]

            probabilities = np.concatenate(batches)
            mode = f"batch_size={batch_size}, workers=1"

        elapsed = perf_counter() - started
        np.testing.assert_allclose(
            probabilities,
            self.reference,
            rtol=1e-10,
            atol=1e-12,
        )
        return BenchmarkResult(mode, len(self.texts), elapsed)


def main():
    """
        - Accept the
            - workload size
            - concurrent worker count.
        - Train once and compare three inference modes.
        - Print throughput for the current machine and workload.
    """
    parser = argparse.ArgumentParser(description="Measure sentiment inference.")
    parser.add_argument("--texts", type=int, default=300)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    if args.texts < 1 or args.batch_size < 1 or args.workers < 1:
        parser.error("texts, batch-size, and workers must be positive.")

    predictor = train_from_file(TRAINING_DATA).predictor

    samples = (
        "This is excellent",
        "This is terrible",
        "The package arrived on Tuesday",
    )

    texts = [samples[index % len(samples)] for index in range(args.texts)]
    benchmark = InferenceBenchmark(predictor.pipeline, texts)

    modes = ((1, 1), (args.batch_size, 1), (1, args.workers))
    for batch_size, workers in modes:
        result = benchmark.run(batch_size, workers)
        throughput = result.text_count / result.elapsed_seconds
        print(
            f"{result.mode} | "
            f"{result.elapsed_seconds:.4f} seconds | "
            f"{throughput:.1f} texts/second"
        )

    print("PASS | All execution modes returned equivalent probabilities.")

if __name__ == "__main__":
    main()
