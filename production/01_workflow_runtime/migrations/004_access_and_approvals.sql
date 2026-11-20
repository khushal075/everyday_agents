-- Apply once after 003_retry_scheduling.sql on a dedicated connection,
-- outside any transaction, with the API and workers stopped.
-- Foreign keys are disabled while rebuilding the referenced jobs table.
PRAGMA foreign_keys = OFF;

BEGIN IMMEDIATE;

CREATE TABLE feedback_jobs_new (
    job_id TEXT PRIMARY KEY NOT NULL,
    feedback_text TEXT NOT NULL CHECK (length(trim(feedback_text)) > 0),
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN (
            'queued', 'running', 'awaiting_approval', 'completed', 'failed'
        )),
    action TEXT CHECK (action IN ('record', 'prepare_review')),
    reason TEXT,
    error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    claim_token TEXT,
    lease_expires_at REAL,
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    retry_at REAL NOT NULL DEFAULT 0,
    tenant_id TEXT NOT NULL DEFAULT 'local'
        CHECK (length(trim(tenant_id)) > 0),
    UNIQUE (job_id, tenant_id),
    CHECK (status <> 'completed' OR (action IS NOT NULL AND reason IS NOT NULL)),
    CHECK (status <> 'failed' OR error IS NOT NULL)
);

-- Preserve all fields introduced by migrations 001 through 003.
INSERT INTO feedback_jobs_new (
    job_id, feedback_text, status, action, reason, error,
    created_at, updated_at, claim_token, lease_expires_at,
    attempt_count, retry_at, tenant_id
)
SELECT
    job_id, feedback_text, status, action, reason, error,
    created_at, updated_at, claim_token, lease_expires_at,
    attempt_count, retry_at, 'local'
FROM feedback_jobs;

DROP TABLE feedback_jobs;
ALTER TABLE feedback_jobs_new RENAME TO feedback_jobs;

CREATE INDEX feedback_jobs_queue
    ON feedback_jobs (created_at, job_id)
    WHERE status = 'queued';

CREATE INDEX feedback_jobs_expired_leases
    ON feedback_jobs (lease_expires_at)
    WHERE status = 'running';

CREATE INDEX feedback_jobs_tenant
    ON feedback_jobs (tenant_id, created_at, job_id);

CREATE TABLE action_requests (
    operation_id TEXT PRIMARY KEY NOT NULL
        CHECK (length(trim(operation_id)) > 0),
    job_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL CHECK (length(trim(tenant_id)) > 0),
    action TEXT NOT NULL CHECK (length(trim(action)) > 0),
    parameters_json TEXT NOT NULL
        CHECK (json_valid(parameters_json))
        CHECK (json_type(parameters_json) = 'object'),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (operation_id, tenant_id),
    FOREIGN KEY (job_id, tenant_id)
        REFERENCES feedback_jobs (job_id, tenant_id)
);

CREATE INDEX action_requests_job ON action_requests (job_id, tenant_id);

CREATE TABLE approval_records (
    approval_id TEXT PRIMARY KEY NOT NULL
        CHECK (length(trim(approval_id)) > 0),
    operation_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('approved', 'rejected')),
    approved_by TEXT NOT NULL CHECK (length(trim(approved_by)) > 0),
    decided_at TEXT NOT NULL CHECK (length(trim(decided_at)) > 0),
    UNIQUE (operation_id, tenant_id),
    FOREIGN KEY (operation_id, tenant_id)
        REFERENCES action_requests (operation_id, tenant_id)
);

-- Preserve the exact proposal referenced by an approval.
-- Changed action details require a new operation ID.
CREATE TRIGGER action_requests_immutable_update
BEFORE UPDATE ON action_requests
BEGIN
    SELECT RAISE(ABORT, 'Action requests are immutable');
END;

CREATE TRIGGER action_requests_immutable_delete
BEFORE DELETE ON action_requests
BEGIN
    SELECT RAISE(ABORT, 'Action requests are immutable');
END;

CREATE TRIGGER approval_records_immutable_update
BEFORE UPDATE ON approval_records
BEGIN
    SELECT RAISE(ABORT, 'Approval decisions are immutable');
END;

CREATE TRIGGER approval_records_immutable_delete
BEFORE DELETE ON approval_records
BEGIN
    SELECT RAISE(ABORT, 'Approval decisions are immutable');
END;

COMMIT;

PRAGMA foreign_keys = ON;
PRAGMA foreign_key_check;
