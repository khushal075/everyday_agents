-- Preserve existing sentiment jobs while enabling durable policy routing.
BEGIN IMMEDIATE;
ALTER TABLE feedback_jobs ADD COLUMN workflow_mode TEXT NOT NULL DEFAULT 'sentiment'
    CHECK (workflow_mode IN ('sentiment', 'policy'));
ALTER TABLE review_records ADD COLUMN operation_id TEXT REFERENCES action_requests(operation_id);
ALTER TABLE review_records ADD COLUMN route TEXT CHECK (route IN ('billing_review', 'account_support'));
ALTER TABLE review_records ADD COLUMN source TEXT;
ALTER TABLE review_records ADD COLUMN heading TEXT;
ALTER TABLE review_records ADD COLUMN reason TEXT;
CREATE UNIQUE INDEX review_records_operation ON review_records(operation_id)
    WHERE operation_id IS NOT NULL;
COMMIT;
