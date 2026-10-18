-- Idempotency Records
CREATE TABLE idempotency_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    user_id UUID NOT NULL
        REFERENCES users(id) ON DELETE CASCADE,

    idempotency_key VARCHAR(255) NOT NULL,
    request_hash VARCHAR(64) NOT NULL,

    response_status INTEGER,
    response_body JSONB,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMPTZ NOT NULL,

    CONSTRAINT uq_idempotency_user_key
        UNIQUE (user_id, idempotency_key),

    CONSTRAINT chk_idempotency_expiry
        CHECK (expires_at > created_at),

    CONSTRAINT chk_idempotency_response
        CHECK (
            (response_status IS NULL AND response_body IS NULL)
            OR
            (response_status IS NOT NULL AND response_body IS NOT NULL)
        )
);

CREATE INDEX idx_idempotency_records_expires_at
    ON idempotency_records (expires_at);