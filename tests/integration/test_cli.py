"""Exercise public module/console commands and their error contracts."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from everyday_agents.cli import main


_ROOT = Path(__file__).resolve().parents[2]
_SAMPLE = _ROOT / "data/samples/sentiment/feedback.jsonl"


class CliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.model = Path(cls.temporary.name) / "model"
        completed = cls.run_command(
            "sentiment", "train", "--data", str(_SAMPLE), "--output", str(cls.model),
        )
        if completed.returncode:
            raise AssertionError(completed.stderr)
        cls.training_report = json.loads(completed.stdout)

    @staticmethod
    def run_command(*arguments):
        return subprocess.run(
            [sys.executable, "-m", "everyday_agents", *arguments],
            cwd=_ROOT, capture_output=True, text=True,
        )

    def test_version_and_help(self):
        version = self.run_command("--version")
        self.assertEqual(version.returncode, 0, version.stderr)
        self.assertEqual(version.stdout.strip(), "everyday-agents 0.1.0")
        help_result = self.run_command("sentiment", "--help")
        self.assertEqual(help_result.returncode, 0)
        for command in ("run", "train", "evaluate"):
            self.assertIn(command, help_result.stdout)

    def test_console_entrypoint_is_installed(self):
        suffix = ".exe" if sys.platform == "win32" else ""
        console = Path(sys.executable).with_name("everyday-agents" + suffix)
        result = subprocess.run([str(console), "--version"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("0.1.0", result.stdout)

    def test_baseline_run_emits_one_complete_json_object(self):
        result = self.run_command("sentiment", "run", "--text", "This is terrible")
        self.assertEqual(result.returncode, 0, result.stderr)
        run = json.loads(result.stdout)
        self.assertEqual(run["prediction"]["sentiment"], "negative")
        self.assertEqual(run["decision"]["action"], "prepare_review")
        self.assertTrue(run["result"]["success"])

    def test_saved_model_runs_without_training(self):
        result = self.run_command("sentiment", "run", "--model", str(self.model), "--text", "Great service")
        self.assertEqual(result.returncode, 0, result.stderr)
        run = json.loads(result.stdout)
        self.assertIn("probabilities", run["prediction"])
        self.assertTrue(run["result"]["success"])

    def test_training_report_includes_validation_and_not_test(self):
        self.assertIn("validation", self.training_report)
        self.assertNotIn("test", self.training_report)
        self.assertEqual(self.training_report["training_rows"], 58)
        self.assertEqual(self.training_report["artifact"], str(self.model))

    def test_evaluate_uses_explicit_data_without_fitting(self):
        path = Path(self.temporary.name) / "evaluation.jsonl"
        path.write_text('{"text":"great", "label":"positive"}\n'
                        '{"text":"terrible", "label":"negative"}\n', encoding="utf-8")
        output = io.StringIO()
        with patch("everyday_agents.agents.sentiment.train.SentimentTrainer.train",
                   side_effect=AssertionError("Evaluation must not train")), redirect_stdout(output):
            main(["sentiment", "evaluate", "--model", str(self.model), "--data", str(path)])
        report = json.loads(output.getvalue())
        self.assertEqual(report["evaluation"]["learned"]["sample_count"], 2)
        self.assertEqual(report["evaluation"]["baseline"]["accuracy"], 1.0)

    def test_invalid_input_unknown_commands_and_missing_files_have_clean_errors(self):
        for arguments in (
            (), ("unknown",), ("sentiment", "run"),
            ("sentiment", "run", "--text", "  "),
            ("sentiment", "evaluate", "--model", str(self.model)),
            ("sentiment", "run", "--model", str(self.model / "missing"), "--text", "good"),
        ):
            with self.subTest(arguments=arguments):
                result = self.run_command(*arguments)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertIn("error:", result.stderr)
                self.assertNotIn("Traceback", result.stderr)

    def test_train_refuses_to_overwrite_saved_model(self):
        original = (self.model / "model").read_bytes()
        result = self.run_command("sentiment", "train", "--data", str(_SAMPLE), "--output", str(self.model))
        self.assertEqual(result.returncode, 2)
        self.assertIn("already exists", result.stderr)
        self.assertEqual((self.model / "model").read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
