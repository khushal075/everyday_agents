"""Check artifact round trips, overwrite protection, and failure boundaries."""

from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from everyday_agents.ml.artifacts import ModelMetadata, load_artifact, save_artifact


def write_model(model: dict, path: Path) -> None:
    path.write_text(json.dumps(model), encoding="utf-8")


def read_model(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.destination = Path(self.temporary.name) / "models" / "example-v1"
        self.metadata = ModelMetadata(
            model_name="example", model_version="1.0",
            input_format="One numeric value", output_format="Centered numeric value",
        )
        self.model = {"center": 3.0}

    def save(self):
        return save_artifact(self.model, self.destination, self.metadata, serializer=write_model)

    def test_roundtrip_retains_model_and_metadata(self):
        self.assertEqual(self.save(), self.destination)
        loaded = load_artifact(self.destination, deserializer=read_model)
        self.assertEqual(loaded.model, self.model)
        self.assertEqual(loaded.metadata, self.metadata)

    def test_existing_destination_is_never_overwritten(self):
        self.save()
        before = {p.name: p.read_bytes() for p in self.destination.iterdir()}
        serializer = Mock()
        with self.assertRaises(FileExistsError):
            save_artifact({}, self.destination, self.metadata, serializer=serializer)
        serializer.assert_not_called()
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.destination.iterdir()})

    def test_existing_empty_directory_is_also_protected(self):
        self.destination.mkdir(parents=True)
        with self.assertRaises(FileExistsError):
            self.save()
        self.assertEqual(list(self.destination.iterdir()), [])

    def test_serializer_failure_cleans_partial_artifact_and_propagates(self):
        error = RuntimeError("serialization failed")
        def broken_serializer(model, path):
            path.write_text("partial", encoding="utf-8")
            raise error
        with self.assertRaises(RuntimeError) as raised:
            save_artifact(self.model, self.destination, self.metadata, serializer=broken_serializer)
        self.assertIs(raised.exception, error)
        self.assertFalse(self.destination.exists())

    def test_serializer_must_produce_a_regular_file(self):
        for serializer, error in ((lambda model, path: None, FileNotFoundError),
                                  (lambda model, path: path.mkdir(), ValueError)):
            with self.subTest(error=error), self.assertRaises(error):
                save_artifact(self.model, self.destination, self.metadata, serializer=serializer)
            self.assertFalse(self.destination.exists())

    def test_missing_files_are_rejected_before_deserialization(self):
        self.save()
        for missing in ("model", "metadata.json"):
            with self.subTest(missing=missing):
                removed = self.destination / missing
                content = removed.read_bytes()
                removed.unlink()
                loader = Mock()
                with self.assertRaises(FileNotFoundError):
                    load_artifact(self.destination, deserializer=loader)
                loader.assert_not_called()
                removed.write_bytes(content)

    def test_invalid_manifest_is_rejected_before_deserialization(self):
        self.save()
        valid = {"schema_version": 1, "metadata": asdict(self.metadata)}
        cases = ["{broken", "[]", json.dumps({**valid, "schema_version": 2}),
                 json.dumps({**valid, "schema_version": True}),
                 json.dumps({"schema_version": 1, "metadata": {}}),
                 json.dumps({**valid, "metadata": {k: v for k, v in asdict(self.metadata).items() if k != "created_at"}}),
                 json.dumps({**valid, "metadata": {**asdict(self.metadata), "model_version": 4}})]
        loader = Mock()
        for content in cases:
            with self.subTest(content=content):
                (self.destination / "metadata.json").write_text(content, encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_artifact(self.destination, deserializer=loader)
        loader.assert_not_called()

    def test_invalid_metadata_is_rejected(self):
        for override in ({"model_name": " "}, {"model_version": 1},
                         {"created_at": "yesterday"}, {"created_at": "2026-11-06T12:00:00"}):
            with self.subTest(override=override), self.assertRaises(ValueError):
                ModelMetadata(**{**asdict(self.metadata), **override})

    def test_loader_failure_propagates_without_modifying_artifact(self):
        self.save()
        error = RuntimeError("incompatible model")
        with self.assertRaises(RuntimeError) as raised:
            load_artifact(self.destination, deserializer=Mock(side_effect=error))
        self.assertIs(raised.exception, error)
        self.assertEqual(load_artifact(self.destination, deserializer=read_model).model, self.model)


if __name__ == "__main__":
    unittest.main()
