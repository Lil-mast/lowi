-- Durable recording metadata and pipeline runs.

ALTER TABLE recordings ADD COLUMN storage_backend VARCHAR(32) NOT NULL DEFAULT 'local';
ALTER TABLE recordings ADD COLUMN storage_key VARCHAR(1000);
ALTER TABLE recordings ADD COLUMN content_type VARCHAR(255);
ALTER TABLE recordings ADD COLUMN size_bytes INTEGER;
ALTER TABLE recordings ADD COLUMN checksum_sha256 VARCHAR(64);
ALTER TABLE recordings ADD COLUMN source VARCHAR(32) NOT NULL DEFAULT 'upload';

CREATE INDEX IF NOT EXISTS ix_recordings_storage_key ON recordings (storage_key);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id VARCHAR(36) PRIMARY KEY,
    meeting_id VARCHAR(36) NOT NULL REFERENCES meetings(id),
    kind VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'queued',
    attempts INTEGER NOT NULL DEFAULT 0,
    job_id VARCHAR(255),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    duration_ms INTEGER,
    error_code VARCHAR(64),
    error_message VARCHAR(1000),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_pipeline_runs_meeting_status
    ON pipeline_runs (meeting_id, status);
CREATE INDEX IF NOT EXISTS ix_pipeline_runs_status_started
    ON pipeline_runs (status, started_at);
