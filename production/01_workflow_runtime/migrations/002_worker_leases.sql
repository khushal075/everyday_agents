-- Apply once after 001_initial.sql, with the API and worker stopped.

BEGIN;

ALTER TABLE feedback_jobs ADD COLUMN claim_token TEXT;

-- Unix timestamp in seconds.
ALTER TABLE feedback_jobs ADD COLUMN lease_expires_at REAL;

ALTER TABLE feedback_jobs
    ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0
    CHECK (attempt_count >= 0);

-- Jobs left running before leases existed become eligible for recovery.
UPDATE feedback_jobs
SET lease_expires_at = 0
WHERE status = 'running';

CREATE INDEX feedback_jobs_expired_leases
    ON feedback_jobs (lease_expires_at)
    WHERE status = 'running';

COMMIT;