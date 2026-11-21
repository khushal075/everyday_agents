"""Verify migration safety and operational failure detection."""

import io
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path
from time import time

from production.category_04_evaluation_and_observability.telemetry import Telemetry
from production.category_05_deployment_and_operations.check_alerts import AlertChecker, AlertRules
from production.category_05_deployment_and_operations.healthcheck import check_database, check_worker
from production.category_05_deployment_and_operations.migrate import MIGRATIONS, MigrationRunner


class ProductionOperationsTests(unittest.TestCase):
    """Exercise database safety boundaries and observable operational failures."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.database = self.root / "workflow.sqlite3"
        self.runner = MigrationRunner(self.database)

    def tearDown(self):
        self.directory.cleanup()

    def migrate(self):
        with redirect_stdout(io.StringIO()):
            self.runner.run()

    def test_migrations_are_repeatable_and_detect_modified_history(self):
        self.migrate()
        self.migrate()
        check_database(self.database)
        with closing(sqlite3.connect(self.database)) as connection:
            count = connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
            self.assertEqual(count, len(list(MIGRATIONS.glob("*.sql"))))
            connection.execute("UPDATE schema_migrations SET checksum = 'modified'")
            connection.commit()
        with self.assertRaisesRegex(ValueError, "modified"):
            self.runner.run()

    def test_manual_adoption_preserves_reviews_and_pending_migrations(self):
        with closing(sqlite3.connect(self.database)) as connection:
            for path in sorted(MIGRATIONS.glob("*.sql"))[:3]:
                connection.executescript(path.read_text())
            connection.execute(
                """
                INSERT INTO feedback_jobs(job_id,feedback_text,status,action,reason)
                VALUES ('existing','Terrible','completed','prepare_review','Review')
                """
            )
            connection.execute("INSERT INTO review_records(job_id) VALUES ('existing')")
            connection.commit()
        with self.assertRaisesRegex(ValueError, "adopt-existing"):
            self.runner.run()
        with redirect_stdout(io.StringIO()):
            self.runner.run(adopt_existing=True)
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute(
                "SELECT tenant_id FROM feedback_jobs WHERE job_id='existing'"
            ).fetchone()[0], "local")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM review_records").fetchone()[0], 1)
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_failed_migration_rolls_back_schema_and_history(self):
        self.migrate()
        path = self.root / "006_broken.sql"
        path.write_text("BEGIN; CREATE TABLE rolled_back(id INTEGER); INVALID SQL; COMMIT;")
        with closing(sqlite3.connect(self.database, isolation_level=None)) as connection:
            with self.assertRaises(sqlite3.Error):
                self.runner.apply(connection, path)
            self.assertIsNone(connection.execute(
                "SELECT name FROM sqlite_master WHERE name='rolled_back'"
            ).fetchone())
            self.assertIsNone(connection.execute(
                "SELECT filename FROM schema_migrations WHERE filename=?", (path.name,)
            ).fetchone())

    def test_unknown_manual_schema_is_rejected(self):
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute("CREATE TABLE unknown(id INTEGER)")
        with self.assertRaisesRegex(ValueError, "differs"):
            self.runner.run(adopt_existing=True)

    def test_health_rejects_stale_heartbeat_and_missing_database(self):
        heartbeat = self.root / "heartbeat.json"
        heartbeat.write_text(json.dumps({"pid": os.getpid(), "timestamp": time()}))
        check_worker(heartbeat, 60)
        heartbeat.write_text(json.dumps({"pid": os.getpid(), "timestamp": time() - 120}))
        with self.assertRaises(ValueError):
            check_worker(heartbeat, 60)
        with self.assertRaises(sqlite3.Error):
            check_database(self.database)
        self.assertFalse(self.database.exists())

    def test_alerts_detect_stalled_jobs_failures_and_latency(self):
        self.migrate()
        event_database = self.root / "events.sqlite3"
        telemetry = Telemetry(stream=io.StringIO(), database_path=event_database)
        rules = AlertRules(
            window_seconds=300, minimum_events=2, failure_rate=0.2,
            api_p95_ms=100, queued_age_seconds=60,
            expired_lease_grace_seconds=10, approval_age_seconds=60,
        )
        checker = AlertChecker(self.database, event_database, rules)
        self.assertEqual(checker.check(), [])
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute(
                """
                INSERT INTO feedback_jobs(job_id,feedback_text,created_at)
                VALUES ('old','Feedback','2000-01-01 00:00:00')
                """
            )
            connection.commit()
        for _ in range(2):
            telemetry.emit(run_id="run", stage="api.submit_feedback", outcome="failed", duration_ms=200)
        active = {alert["rule"] for alert in checker.check()}
        self.assertEqual(active, {"old_queued_jobs", "stage_failure_rate", "api_p95_latency"})
