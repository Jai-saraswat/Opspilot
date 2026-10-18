-- Login Sessions
CREATE TABLE login_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    user_id UUID NOT NULL
        REFERENCES users(id) ON DELETE CASCADE,

    refresh_token_hash TEXT NOT NULL UNIQUE,

    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_login_sessions_expiry
        CHECK (expires_at > created_at),

    CONSTRAINT chk_login_sessions_revocation
        CHECK (revoked_at IS NULL OR revoked_at >= created_at)
);

CREATE INDEX idx_login_sessions_user_id
    ON login_sessions (user_id);

CREATE INDEX idx_login_sessions_expires_at
    ON login_sessions (expires_at);