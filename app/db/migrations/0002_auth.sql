-- Authentication: link local users to Neon Auth and add opaque LoWi sessions.

ALTER TABLE users ADD COLUMN neon_auth_user_id VARCHAR(255);
ALTER TABLE users ADD COLUMN last_login_at TIMESTAMPTZ;

CREATE UNIQUE INDEX IF NOT EXISTS ix_users_neon_auth_user_id
    ON users (neon_auth_user_id);

CREATE TABLE IF NOT EXISTS sessions (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash VARCHAR(64) NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMPTZ,
    user_agent VARCHAR(500),
    ip VARCHAR(64)
);

CREATE INDEX IF NOT EXISTS ix_sessions_user_id ON sessions (user_id);
CREATE INDEX IF NOT EXISTS ix_sessions_token_hash ON sessions (token_hash);
CREATE INDEX IF NOT EXISTS ix_sessions_expires_at ON sessions (expires_at);
