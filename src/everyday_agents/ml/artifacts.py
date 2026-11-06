"""Model-independent artifact persistence with explicit serialization callbacks.

Each artifact directory contains a model file and metadata.json. Callers supply
serialization compatible with their model library. Only load trusted artifacts:
metadata validation does not make a deserializer safe for untrusted files.
"""

from collections.abc import Callable
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil


_SCHEMA_VERSION = 1
_MODEL_FILE = "model"
_METADATA_FILE = "metadata.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ModelMetadata:
    """Human-readable model identity and input/output contract descriptions.

    created_at is an ISO 8601 timestamp with a timezone. Format descriptions
    document expected inputs/outputs; this module does not validate inference.
    """

    model_name: str
    model_version: str
    input_format: str
    output_format: str
    created_at: str = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        for name in ("model_name", "model_version", "input_format", "output_format", "created_at"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Metadata {name} must be a non-empty string")
        try:
            timestamp = datetime.fromisoformat(self.created_at)
        except ValueError as exc:
            raise ValueError("Metadata created_at must be an ISO 8601 timestamp") from exc
        if timestamp.tzinfo is None:
            raise ValueError("Metadata created_at must include a timezone")


@dataclass(frozen=True)
class LoadedArtifact[ModelT]:
    model: ModelT
    metadata: ModelMetadata


def save_artifact[ModelT](
    model: ModelT,
    destination: str | Path,
    metadata: ModelMetadata,
    *,
    serializer: Callable[[ModelT, Path], None],
) -> Path:
    """Save to a new directory, refusing to overwrite any existing destination.

    serializer must write one regular file at the supplied path, including all
    fitted preprocessing needed by the model. Its exceptions propagate.

    The directory is reserved before writing. Metadata is written last as the
    completion marker. Failed writes remove the newly created directory; saves
    are not atomic or crash-durable. Parent directories may remain after failure.
    """
    destination = Path(destination)
    # Serialize metadata before creating a directory or invoking user code.
    manifest = json.dumps(
        {"schema_version": _SCHEMA_VERSION, "metadata": asdict(metadata)},
        indent=2,
        allow_nan=False,
    )
    destination.mkdir(parents=True, exist_ok=False)
    try:
        model_path = destination / _MODEL_FILE
        serializer(model, model_path)
        _require_file(model_path)
        with (destination / _METADATA_FILE).open("x", encoding="utf-8") as handle:
            handle.write(manifest + "\n")
    except BaseException:
        # Retain the original write/serializer error if cleanup itself fails.
        shutil.rmtree(destination, ignore_errors=True)
        raise
    return destination


def _require_file(path: Path) -> None:
    if path.is_symlink():
        raise ValueError(f"Artifact file must not be a symbolic link: {path}")
    if not path.exists():
        raise FileNotFoundError(f"Artifact file is missing: {path}")
    if not path.is_file():
        raise ValueError(f"Artifact path must be a regular file: {path}")


def _read_metadata(path: Path) -> ModelMetadata:
    _require_file(path)
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("Artifact metadata must be valid UTF-8 JSON") from exc
    if not isinstance(manifest, dict) or set(manifest) != {"schema_version", "metadata"}:
        raise ValueError("Artifact manifest must contain schema_version and metadata")
    version = manifest["schema_version"]
    if type(version) is not int or version != _SCHEMA_VERSION:
        raise ValueError(f"Unsupported artifact schema version: {version!r}")
    values = manifest["metadata"]
    required = {item.name for item in fields(ModelMetadata)}
    if not isinstance(values, dict) or set(values) != required:
        raise ValueError("Artifact metadata fields do not match ModelMetadata")
    try:
        return ModelMetadata(**values)
    except TypeError as exc:
        raise ValueError("Artifact metadata fields do not match ModelMetadata") from exc


def load_artifact[ModelT](
    source: str | Path,
    *,
    deserializer: Callable[[Path], ModelT],
) -> LoadedArtifact[ModelT]:
    """Validate artifact files and metadata before calling the supplied loader.

    The deserializer must match the serializer used at save time. Library/model
    compatibility and trusted-input requirements remain its responsibility.
    Missing files and deserializer errors propagate to the caller.
    """
    source = Path(source)
    metadata = _read_metadata(source / _METADATA_FILE)
    model_path = source / _MODEL_FILE
    _require_file(model_path)
    return LoadedArtifact(model=deserializer(model_path), metadata=metadata)
