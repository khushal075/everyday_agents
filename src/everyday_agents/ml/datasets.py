"""Load small CSV/JSONL datasets without imposing an agent-specific schema.

CSV values stay strings; JSONL values retain their JSON types. Required fields
check key presence, not types or empty values. Supply a validator for domain
rules. Files are loaded into memory, without shuffling or splitting.
"""

from collections.abc import Callable, Iterator, Mapping, Sequence
import csv
import json
from pathlib import Path
from typing import Any


type Record = dict[str, Any]
type RecordValidator = Callable[[Mapping[str, Any]], None]


def _csv_records(path: Path) -> Iterator[tuple[int, Record]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, strict=True)
        try:
            header = next((row for row in reader if row), None)
            if header is None:
                return
            if any(not name.strip() for name in header) or len(set(header)) != len(header):
                raise ValueError(f"{path}: line {reader.line_num}: CSV headers must be non-empty and unique")
            for values in reader:
                if not values:
                    continue
                if len(values) != len(header):
                    raise ValueError(
                        f"{path}: line {reader.line_num}: expected {len(header)} CSV values, "
                        f"received {len(values)}"
                    )
                yield reader.line_num, dict(zip(header, values))
        except csv.Error as exc:
            raise ValueError(f"{path}: line {reader.line_num}: invalid CSV: {exc}") from exc


def _reject_constant(value: str) -> None:
    raise ValueError(f"Non-standard JSON constant: {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> Record:
    record: Record = {}
    for key, value in pairs:
        if key in record:
            raise ValueError(f"Duplicate JSON key: {key!r}")
        record[key] = value
    return record


def _jsonl_records(path: Path) -> Iterator[tuple[int, Record]]:
    with path.open(encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(
                    line, parse_constant=_reject_constant, object_pairs_hook=_unique_object,
                )
            except ValueError as exc:
                raise ValueError(f"{path}: line {line_number}: invalid JSON: {exc}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"{path}: line {line_number}: JSONL record must be an object")
            yield line_number, record


def load_dataset(
    source: str | Path,
    *,
    required_fields: Sequence[str] = (),
    validator: RecordValidator | None = None,
) -> list[Record]:
    """Load .csv or .jsonl records with optional domain validation.

    CSV supports quoted commas and multiline fields. Blank records are skipped.
    UTF-8 with or without a BOM is accepted. Duplicate field names, malformed
    rows, and empty datasets are rejected. CSV values are not converted; JSON
    non-standard constants such as NaN are rejected.

    A validator checks each record and returns None, raising ValueError or
    TypeError for invalid data. Those errors gain file/line context and retain
    their cause. Other callback exceptions propagate unchanged. Validators
    should not mutate records. Missing-file and other filesystem errors also
    propagate. On any invalid record, no partial dataset is returned.

    Example:
        rows = load_dataset("feedback.jsonl", required_fields=("text", "label"))
    """
    path = Path(source)
    if isinstance(required_fields, (str, bytes)) or any(
        not isinstance(name, str) or not name.strip() for name in required_fields
    ):
        raise ValueError("required_fields must be a sequence of non-empty field names")
    readers = {".csv": _csv_records, ".jsonl": _jsonl_records}
    if path.suffix.lower() not in readers:
        raise ValueError(f"{path}: unsupported dataset format; use .csv or .jsonl")

    records: list[Record] = []
    try:
        for line_number, record in readers[path.suffix.lower()](path):
            missing = [name for name in required_fields if name not in record]
            if missing:
                raise ValueError(f"{path}: line {line_number}: missing required fields: {', '.join(missing)}")
            if validator is not None:
                try:
                    validator(record)
                except (ValueError, TypeError) as exc:
                    raise ValueError(f"{path}: line {line_number}: validation failed: {exc}") from exc
            records.append(record)
    except UnicodeError as exc:
        raise ValueError(f"{path}: dataset must be UTF-8 encoded") from exc
    if not records:
        raise ValueError(f"{path}: dataset contains no records")
    return records
