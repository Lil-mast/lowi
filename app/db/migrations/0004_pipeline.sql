-- Metadata needed for relevance, chunked summaries, and safe errors.

ALTER TABLE meetings ADD COLUMN attendees JSON;
ALTER TABLE meetings ADD COLUMN project VARCHAR(255);
ALTER TABLE meetings ADD COLUMN error_code VARCHAR(64);
ALTER TABLE meetings ADD COLUMN error_message VARCHAR(1000);
ALTER TABLE meetings ADD COLUMN pipeline_version INTEGER NOT NULL DEFAULT 1;

ALTER TABLE transcripts ADD COLUMN source VARCHAR(32) NOT NULL DEFAULT 'upload';
ALTER TABLE transcripts ADD COLUMN live_session_id VARCHAR(36);
ALTER TABLE transcripts ADD COLUMN word_count INTEGER;
ALTER TABLE transcripts ADD COLUMN model VARCHAR(255);

ALTER TABLE summaries ADD COLUMN model VARCHAR(255);
ALTER TABLE summaries ADD COLUMN prompt_version VARCHAR(64);
ALTER TABLE summaries ADD COLUMN input_chars INTEGER;
ALTER TABLE summaries ADD COLUMN chunk_count INTEGER;

ALTER TABLE action_items ADD COLUMN source_summary_id VARCHAR(36);
ALTER TABLE action_items ADD COLUMN stable_key VARCHAR(64);
ALTER TABLE action_items ADD COLUMN updated_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS ix_action_items_stable_key ON action_items (stable_key);
CREATE INDEX IF NOT EXISTS ix_transcripts_source ON transcripts (source);
