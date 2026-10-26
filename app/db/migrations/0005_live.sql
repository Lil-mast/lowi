-- Live browser capture sessions and committed segments.

CREATE TABLE IF NOT EXISTS live_sessions (
    id VARCHAR(36) PRIMARY KEY,
    meeting_id VARCHAR(36) NOT NULL REFERENCES meetings(id),
    user_id VARCHAR(36) NOT NULL REFERENCES users(id),
    status VARCHAR(32) NOT NULL DEFAULT 'recording',
    source VARCHAR(32) NOT NULL DEFAULT 'mic',
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMPTZ,
    duration_seconds DOUBLE PRECISION,
    audio_bytes INTEGER,
    error_code VARCHAR(64),
    error_message VARCHAR(1000),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS live_segments (
    id VARCHAR(36) PRIMARY KEY,
    live_session_id VARCHAR(36) NOT NULL REFERENCES live_sessions(id),
    meeting_id VARCHAR(36) NOT NULL REFERENCES meetings(id),
    sequence INTEGER NOT NULL,
    text TEXT NOT NULL,
    is_final BOOLEAN NOT NULL DEFAULT TRUE,
    start_ms INTEGER,
    end_ms INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_live_sessions_meeting_status
    ON live_sessions (meeting_id, status);
CREATE INDEX IF NOT EXISTS ix_live_segments_session_sequence
    ON live_segments (live_session_id, sequence);
