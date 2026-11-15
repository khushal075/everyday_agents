-- Apply once to a new database. Enable foreign keys on each application connection.
PRAGMA foreign_keys = ON;

BEGIN;

CREATE TABLE feedback_jobs (
    job_id TEXT PRIMARY KEY NOT NULL,
    feedback_text TEXT NOT NULL CHECK (length(trim(feedback_text)) > 0),
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'completed', 'failed')),
    action TEXT CHECK (action IN ('record', 'prepare_review')),
    reason TEXT,
    error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (status <> 'completed' OR (action IS NOT NULL AND reason IS NOT NULL)),
    CHECK (status <> 'failed' OR error IS NOT NULL)
);

CREATE INDEX feedback_jobs_queue
    ON feedback_jobs (created_at, job_id)
    WHERE status = 'queued';

CREATE TABLE review_records (
    -- One review per job. Read the original feedback text from feedback_jobs.
    job_id TEXT PRIMARY KEY NOT NULL REFERENCES feedback_jobs (job_id),
    status TEXT NOT NULL DEFAULT 'pending_review'
        CHECK (status = 'pending_review'),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMIT;
