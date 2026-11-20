-- Apply once after 002_worker_leases.sql.
BEGIN;
-- Unix timestamp. Zero means immediately eligible.
ALTER TABLE feedback_jobs ADD COLUMN retry_at REAL NOT NULL DEFAULT 0;
COMMIT;
