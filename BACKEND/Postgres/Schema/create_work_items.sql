-- Work Items
CREATE TABLE work_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    title VARCHAR(200) NOT NULL,
    description TEXT NOT NULL,

    type VARCHAR(30) NOT NULL
        CHECK (type IN ('investigation', 'action', 'incident', 'approval')),

    status VARCHAR(30) NOT NULL DEFAULT 'open'
        CHECK (status IN (
            'open',
            'in_progress',
            'pending_approval',
            'resolved',
            'cancelled'
        )),

    priority VARCHAR(20) NOT NULL DEFAULT 'medium'
        CHECK (priority IN ('low', 'medium', 'high', 'critical')),

    team_id UUID NOT NULL
        REFERENCES teams(id) ON DELETE RESTRICT,

    created_by UUID NOT NULL
        REFERENCES users(id) ON DELETE RESTRICT,

    assignee_id UUID
        REFERENCES users(id) ON DELETE RESTRICT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ,

    CONSTRAINT chk_work_items_title
        CHECK (LENGTH(TRIM(title)) > 0),

    CONSTRAINT chk_work_items_description
        CHECK (LENGTH(TRIM(description)) > 0),

    CONSTRAINT chk_work_items_completed_at
        CHECK (
            (status = 'resolved' AND completed_at IS NOT NULL)
            OR
            (status <> 'resolved' AND completed_at IS NULL)
        )
);

-- Work Item Indexes
CREATE INDEX idx_work_items_team_updated
    ON work_items (team_id, updated_at DESC);

CREATE INDEX idx_work_items_assignee_status
    ON work_items (assignee_id, status)
    WHERE assignee_id IS NOT NULL;

CREATE INDEX idx_work_items_team_priority
    ON work_items (team_id, priority);

CREATE INDEX idx_work_items_team_status
    ON work_items (team_id, status);

CREATE INDEX idx_work_items_created_by
    ON work_items (created_by);