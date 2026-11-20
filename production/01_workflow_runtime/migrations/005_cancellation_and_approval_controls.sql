-- Apply once after 004_access_and_approvals.sql.
BEGIN;
ALTER TABLE feedback_jobs ADD COLUMN approval_required INTEGER NOT NULL DEFAULT 0
    CHECK (approval_required IN (0, 1));
ALTER TABLE feedback_jobs ADD COLUMN cancellation_requested INTEGER NOT NULL DEFAULT 0
    CHECK (cancellation_requested IN (0, 1));
COMMIT;
