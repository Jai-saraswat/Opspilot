-- Work Item Activity History
CREATE TABLE work_item_activity (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    work_item_id UUID NOT NULL
        REFERENCES work_items(id) ON DELETE RESTRICT,

    actor_id UUID
        REFERENCES users(id) ON DELETE SET NULL,

    action VARCHAR(50) NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::JSONB,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_work_item_activity_action
        CHECK (LENGTH(TRIM(action)) > 0)
);

CREATE INDEX idx_work_item_activity_item_created
    ON work_item_activity (work_item_id, created_at DESC);

CREATE INDEX idx_work_item_activity_actor
    ON work_item_activity (actor_id, created_at DESC);