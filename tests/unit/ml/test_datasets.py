"""Check dataset format handling and actionable validation failures."""

from pathlib import Path
import tempfile
import unittest

from everyday_agents.ml.datasets import load_dataset
from everyday_agents.ml.splitting import split_dataset


class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def write(self, name, text):
        path = Path(self.directory.name) / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_csv_handles_quotes_multiline_and_preserves_strings(self):
        path = self.write("records.csv", '\ufefftext,label,count\n"Good, helpful",positive,2\n"Two\nlines",uncertain,0\n')
        rows = load_dataset(path, required_fields=("text", "label"))
        self.assertEqual(rows, [
            {"text": "Good, helpful", "label": "positive", "count": "2"},
            {"text": "Two\nlines", "label": "uncertain", "count": "0"},
        ])

    def test_jsonl_preserves_types_and_skips_blank_lines(self):
        path = self.write("records.JSONL", '\ufeff{"value": 2, "flag": true, "extra": null}\n\n{"value": 3}\n')
        self.assertEqual(load_dataset(path, required_fields=("value",)), [
            {"value": 2, "flag": True, "extra": None}, {"value": 3},
        ])

    def test_missing_required_fields_identify_file_and_line(self):
        for name, content, line in (
            ("records.csv", "text,label\ngood,positive\n", 2),
            ("records.jsonl", '\n{"text":"good"}\n', 2),
        ):
            with self.subTest(name=name):
                path = self.write(name, content)
                with self.assertRaisesRegex(ValueError, f"line {line}: missing required fields: id") as raised:
                    load_dataset(path, required_fields=("id",))
                self.assertIn(str(path), str(raised.exception))

    def test_invalid_csv_rows_are_rejected(self):
        for text in ("text,text\na,b\n", "text,\na,b\n", "text,label\na\n",
                     "text,label\na,b,c\n", 'text,label\n"unterminated,b\n'):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "line"):
                load_dataset(self.write("bad.csv", text))

    def test_invalid_json_records_are_rejected(self):
        for text in ('{bad}\n', '[]\n', 'null\n', '{"x":NaN}\n', '{"x":1,"x":2}\n'):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "line 1"):
                load_dataset(self.write("bad.jsonl", text))

    def test_empty_datasets_are_rejected(self):
        for name, text in (("empty.csv", ""), ("header.csv", "text,label\n"),
                           ("empty.jsonl", "\n\n")):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "no records"):
                load_dataset(self.write(name, text))

    def test_domain_validation_errors_keep_cause_and_line(self):
        error = ValueError("text must be non-empty")
        def validator(record):
            if not record["text"]:
                raise error
        path = self.write("records.jsonl", '{"text":"good"}\n{"text":""}\n')
        with self.assertRaisesRegex(ValueError, "line 2: validation failed") as raised:
            load_dataset(path, required_fields=("text",), validator=validator)
        self.assertIs(raised.exception.__cause__, error)

    def test_unexpected_validator_errors_propagate(self):
        error = RuntimeError("validator bug")
        def validator(record):
            raise error
        with self.assertRaises(RuntimeError) as raised:
            load_dataset(self.write("record.jsonl", '{"x":1}\n'), validator=validator)
        self.assertIs(raised.exception, error)

    def test_required_fields_do_not_impose_value_rules(self):
        rows = load_dataset(self.write("record.jsonl", '{"text":null}\n'), required_fields=("text",))
        self.assertEqual(rows, [{"text": None}])

    def test_bad_format_missing_file_and_encoding(self):
        with self.assertRaisesRegex(ValueError, "unsupported dataset format"):
            load_dataset(self.write("data.txt", "x"))
        with self.assertRaises(FileNotFoundError):
            load_dataset(Path(self.directory.name) / "missing.csv")
        path = Path(self.directory.name) / "bad.csv"
        path.write_bytes(b"text\n\xff\n")
        with self.assertRaisesRegex(ValueError, "UTF-8"):
            load_dataset(path)

    def test_bad_required_fields_are_rejected(self):
        path = self.write("record.jsonl", '{"x":1}\n')
        for fields in ("text", [""], [1]):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                load_dataset(path, required_fields=fields)

    def test_loaded_records_work_with_splitter(self):
        path = self.write("records.csv", "id,text\n" + "".join(f"{i},sample {i}\n" for i in range(10)))
        rows = load_dataset(path, required_fields=("id", "text"))
        split = split_dataset(rows)
        self.assertEqual((len(split.train), len(split.validation), len(split.test)), (8, 1, 1))
        self.assertEqual({r["id"] for r in split.train + split.validation + split.test},
                         {str(i) for i in range(10)})


if __name__ == "__main__":
    unittest.main()
