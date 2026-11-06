"""Persist real fitted pipelines and exercise loading without retraining."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import joblib
from sklearn.pipeline import Pipeline

from everyday_agents.agents.sentiment import create_agent
from everyday_agents.agents.sentiment.predictor import load_predictor, save_predictor
from everyday_agents.agents.sentiment.train import train_from_file


_ROOT = Path(__file__).resolve().parents[2]
_SAMPLE = _ROOT / "data/samples/sentiment/feedback.jsonl"


class ModelRoundtripTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.trained = train_from_file(_SAMPLE)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.artifact = Path(self.temporary.name) / "sentiment-v1"

    def test_probabilities_and_agent_actions_survive_save_load_without_fitting(self):
        save_predictor(self.trained.predictor, self.artifact, model_version="demo-1")
        with patch.object(Pipeline, "fit", side_effect=AssertionError("Loading must not fit")):
            loaded = load_predictor(self.artifact)
            for text in ("great helpful service", "terrible broken product", "Delivery arrived today"):
                with self.subTest(text=text):
                    before = self.trained.predictor.predict(text)
                    after = loaded.model.predict(text)
                    self.assertEqual(before, after)
                    original_run = create_agent(predictor=self.trained.predictor).run(text)
                    loaded_run = create_agent(predictor=loaded.model).run(text)
                    self.assertEqual(original_run.decision, loaded_run.decision)
                    self.assertTrue(loaded_run.result.success)
        self.assertEqual(loaded.metadata.model_version, "demo-1")

    def test_overwrite_and_missing_model_are_rejected(self):
        save_predictor(self.trained.predictor, self.artifact)
        before = (self.artifact / "model").read_bytes()
        with self.assertRaises(FileExistsError):
            save_predictor(self.trained.predictor, self.artifact)
        self.assertEqual((self.artifact / "model").read_bytes(), before)
        (self.artifact / "model").unlink()
        with self.assertRaises(FileNotFoundError):
            load_predictor(self.artifact)

    def test_incompatible_runtime_and_invalid_bundle_are_rejected(self):
        save_predictor(self.trained.predictor, self.artifact)
        bundle = joblib.load(self.artifact / "model")
        bundle["runtime_versions"]["scikit-learn"] = "different-version"
        joblib.dump(bundle, self.artifact / "model", compress=3)
        with self.assertRaisesRegex(ValueError, "runtime versions differ"):
            load_predictor(self.artifact)
        joblib.dump({"format_version": 99}, self.artifact / "model", compress=3)
        with self.assertRaisesRegex(ValueError, "Invalid sentiment model bundle"):
            load_predictor(self.artifact)

    def test_wrong_model_identity_is_rejected(self):
        save_predictor(self.trained.predictor, self.artifact)
        path = self.artifact / "metadata.json"
        manifest = json.loads(path.read_text())
        manifest["metadata"]["model_name"] = "another-model"
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "does not identify a sentiment model"):
            load_predictor(self.artifact)

    def test_training_command_saves_model_and_reports_validation_only_by_default(self):
        command = [sys.executable, "-m", "everyday_agents.agents.sentiment.train", "--data", str(_SAMPLE)]
        result = subprocess.run(command + ["--output", str(self.artifact)], cwd=_ROOT,
                                capture_output=True, text=True, check=True)
        report = json.loads(result.stdout)
        self.assertIn("validation", report)
        self.assertNotIn("test", report)
        self.assertEqual(report["validation"]["learned"]["sample_count"], 7)
        self.assertEqual(report["validation"]["baseline"]["sample_count"], 7)
        self.assertEqual(report["artifact"], str(self.artifact))
        self.assertIsNotNone(load_predictor(self.artifact).model)
        repeated = subprocess.run(command + ["--output", str(self.artifact)], cwd=_ROOT,
                                  capture_output=True, text=True)
        self.assertNotEqual(repeated.returncode, 0)
        self.assertEqual(repeated.stdout, "")

    def test_final_test_evaluation_requires_explicit_flag(self):
        result = subprocess.run(
            [sys.executable, "-m", "everyday_agents.agents.sentiment.train", "--data", str(_SAMPLE), "--evaluate-test"],
            cwd=_ROOT, capture_output=True, text=True, check=True,
        )
        report = json.loads(result.stdout)
        self.assertEqual(report["test"]["learned"]["sample_count"], 7)
        self.assertEqual(report["test"]["baseline"]["sample_count"], 7)


if __name__ == "__main__":
    unittest.main()
