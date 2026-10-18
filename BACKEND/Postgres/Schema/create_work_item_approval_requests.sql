-- Work Item Approval Requests
CREATE TABLE work_item_approval_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    work_item_id UUID NOT NULL
        REFERENCES work_items(id) ON DELETE RESTRICT,

    requested_by UUID NOT NULL
        REFERENCES users(id) ON DELETE RESTRICT,

    approver_id UUID
        REFERENCES users(id) ON DELETE RESTRICT,

    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected')),

    decision_reason TEXT,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    decided_at TIMESTAMPTZ,

    CONSTRAINT chk_work_item_approval_decision
        CHECK (
            (status = 'pending' AND decided_at IS NULL)
            OR
            (status IN ('approved', 'rejected') AND decided_at IS NOT NULL)
        )
);

CREATE INDEX idx_work_item_approval_pending
    ON work_item_approval_requests (approver_id, requested_at)
    WHERE status = 'pending';

CREATE INDEX idx_work_item_approval_item
    ON work_item_approval_requests (work_item_id, requested_at DESC);