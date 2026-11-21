"""
- Apply ordered SQLite migrations and record their checksums.
- Commit each schema change together with its migration history entry.
- Adopt an existing manual schema only when it matches a known version.
"""

import argparse
import hashlib
import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[1] / "01_workflow_runtime/migrations"


def migration_statements(source: str) -> list[str]:
    """
    - Split complete SQL statements, including trigger bodies.
    - Leave transaction boundaries and foreign-key checks to the runner.
    """
    statements: list[str] = []
    buffer = ""
    controls = {
        "BEGIN", "BEGIN IMMEDIATE", "COMMIT",
        "PRAGMA FOREIGN_KEYS = ON", "PRAGMA FOREIGN_KEYS = OFF",
        "PRAGMA FOREIGN_KEY_CHECK",
    }
    for character in source:
        buffer += character
        if character != ";" or not sqlite3.complete_statement(buffer):
            continue
        executable = re.sub(r"\A(?:\s*--[^\n]*(?:\n|$))*", "", buffer).strip()
        normalized = " ".join(executable.rstrip(";").split()).upper()
        if normalized and normalized not in controls:
            statements.append(buffer)
        buffer = ""
    if re.sub(r"--[^\n]*", "", buffer).strip():
        raise ValueError("Migration ends with an incomplete SQL statement.")
    return statements


class MigrationRunner:
    """
    - Serialize migration writers using SQLite transactions.
    - Verify applied files before applying pending versions.
    """

    def __init__(self, database_path: Path) -> None:
        """
        - Store the workflow database and its migration directory.

        :param database_path: Workflow database path.
        """
        self.database_path = database_path
        self.migrations_path = MIGRATIONS

    def schema(self, connection: sqlite3.Connection) -> list[tuple]:
        """
        - Read the application schema for comparison.
        - Exclude SQLite internals and migration history.
        """
        return connection.execute(
            """
            SELECT type, name, tbl_name, sql FROM sqlite_master
            WHERE name NOT LIKE 'sqlite_%' AND name <> 'schema_migrations'
            ORDER BY type, name
            """
        ).fetchall()

    def apply(self, connection: sqlite3.Connection, path: Path) -> bool:
        """
        - Apply a migration and its history entry atomically.
        - Reject modified applied files and roll back failures.
        """
        source = path.read_bytes()
        checksum = hashlib.sha256(source).hexdigest()
        connection.execute("BEGIN IMMEDIATE")
        try:
            previous = connection.execute(
                "SELECT checksum FROM schema_migrations WHERE filename = ?",
                (path.name,),
            ).fetchone()
            if previous is not None:
                if previous[0] != checksum:
                    raise ValueError(f"Applied migration was modified: {path.name}")
                connection.commit()
                return False
            for statement in migration_statements(source.decode("utf-8")):
                connection.execute(statement)
            violations = connection.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise ValueError(f"Foreign-key violations after {path.name}: {violations}")
            connection.execute(
                "INSERT INTO schema_migrations(filename, checksum) VALUES (?, ?)",
                (path.name, checksum),
            )
            connection.commit()
            return True
        except BaseException:
            connection.rollback()
            raise

    def adopt(self, connection: sqlite3.Connection, paths: list[Path]) -> None:
        """
        - Find the migration prefix matching a manually initialized schema.
        - Record verified files without executing their SQL against user data.
        """
        connection.execute("BEGIN IMMEDIATE")
        try:
            # Another migration runner may have completed while this one waited.
            if connection.execute("SELECT 1 FROM schema_migrations LIMIT 1").fetchone():
                connection.commit()
                return
            existing = self.schema(connection)
            matched: list[Path] | None = None
            with closing(sqlite3.connect(":memory:", isolation_level=None)) as reference:
                reference.execute("PRAGMA foreign_keys = OFF")
                for index, path in enumerate(paths):
                    for statement in migration_statements(path.read_text(encoding="utf-8")):
                        reference.execute(statement)
                    if self.schema(reference) == existing:
                        matched = paths[:index + 1]
            if matched is None:
                raise ValueError("Existing schema differs from every known migration version.")
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                raise ValueError("Existing database has foreign-key violations.")
            for path in matched:
                connection.execute(
                    "INSERT INTO schema_migrations(filename, checksum) VALUES (?, ?)",
                    (path.name, hashlib.sha256(path.read_bytes()).hexdigest()),
                )
            connection.commit()
            print(f"Adopted {len(matched)} existing migrations.")
        except BaseException:
            connection.rollback()
            raise

    def run(self, adopt_existing: bool = False) -> None:
        """
        - Initialize history, validate its order, and apply pending migrations.
        - Require explicit adoption for an existing database without history.
        """
        paths = sorted(self.migrations_path.glob("*.sql"))
        if not paths:
            raise ValueError("No migration files found.")
        with closing(sqlite3.connect(
            self.database_path, timeout=10, isolation_level=None,
        )) as connection:
            # Referenced-table rebuilds require this pragma outside a transaction.
            connection.execute("PRAGMA foreign_keys = OFF")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    filename TEXT PRIMARY KEY NOT NULL,
                    checksum TEXT NOT NULL,
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            history = {
                row[0] for row in connection.execute(
                    "SELECT filename FROM schema_migrations"
                )
            }
            prefix = {path.name for path in paths[:len(history)]}
            if history != prefix:
                raise ValueError("Migration history is not a prefix of the known migrations.")
            if not history and self.schema(connection):
                if not adopt_existing:
                    raise ValueError(
                        "Existing schema has no history. Stop services and use --adopt-existing."
                    )
                self.adopt(connection, paths)
            for path in paths:
                applied = self.apply(connection, path)
                print(f"{'Applied' if applied else 'Already applied'}: {path.name}")


def main() -> int:
    """
    - Accept a database path and optional manual-schema adoption.
    - Return a nonzero exit code on migration failure.
    """
    parser = argparse.ArgumentParser(description="Apply workflow migrations.")
    parser.add_argument("--database", type=Path, default=Path(
        os.environ.get("FEEDBACK_DB_PATH", "feedback-runtime.sqlite3"),
    ))
    parser.add_argument("--adopt-existing", action="store_true")
    args = parser.parse_args()
    try:
        MigrationRunner(args.database).run(args.adopt_existing)
    except (OSError, ValueError, sqlite3.Error) as error:
        print(f"Migration failed: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
