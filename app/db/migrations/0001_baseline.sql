-- Baseline schema for LoWi.
-- Existing installations that already have the meetings table are baselined by
-- the migration runner without re-running this file.

CREATE TABLE IF NOT EXISTS users (
    id VARCHAR(36) PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    discord_webhook_url VARCHAR(500),
    settings JSON,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS meetings (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id),
    title VARCHAR(500) NOT NULL,
    scheduled_at TIMESTAMPTZ,
    status VARCHAR(32) NOT NULL DEFAULT 'scheduled',
    calendar_event_id VARCHAR(255),
    agenda TEXT,
    prep_brief TEXT,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS recordings (
    id VARCHAR(36) PRIMARY KEY,
    meeting_id VARCHAR(36) NOT NULL REFERENCES meetings(id),
    local_path VARCHAR(1000),
    duration_seconds DOUBLE PRECISION,
    status VARCHAR(32) NOT NULL DEFAULT 'stored',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS transcripts (
    id VARCHAR(36) PRIMARY KEY,
    meeting_id VARCHAR(36) NOT NULL REFERENCES meetings(id),
    raw_text TEXT NOT NULL DEFAULT '',
    diarized_json JSON,
    language VARCHAR(32),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS summaries (
    id VARCHAR(36) PRIMARY KEY,
    meeting_id VARCHAR(36) NOT NULL REFERENCES meetings(id),
    structured_json JSON NOT NULL,
    narrative TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS action_items (
    id VARCHAR(36) PRIMARY KEY,
    meeting_id VARCHAR(36) NOT NULL REFERENCES meetings(id),
    description TEXT NOT NULL,
    owner VARCHAR(255),
    due_date DATE,
    status VARCHAR(32) NOT NULL DEFAULT 'open',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_meetings_user_created ON meetings (user_id, created_at);
CREATE INDEX IF NOT EXISTS ix_recordings_meeting_created ON recordings (meeting_id, created_at);
CREATE INDEX IF NOT EXISTS ix_transcripts_meeting_created ON transcripts (meeting_id, created_at);
CREATE INDEX IF NOT EXISTS ix_summaries_meeting_created ON summaries (meeting_id, created_at);
CREATE INDEX IF NOT EXISTS ix_action_items_meeting_status ON action_items (meeting_id, status);
