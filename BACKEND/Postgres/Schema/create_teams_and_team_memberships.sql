-- Teams
CREATE TABLE teams (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    name VARCHAR(100) NOT NULL,
    description TEXT,

    created_by UUID NOT NULL
        REFERENCES users(id) ON DELETE RESTRICT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_teams_name
        CHECK (LENGTH(TRIM(name)) > 0),

    CONSTRAINT uq_teams_name UNIQUE (name)
);

-- Team Memberships
CREATE TABLE team_memberships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    team_id UUID NOT NULL
        REFERENCES teams(id) ON DELETE CASCADE,

    user_id UUID NOT NULL
        REFERENCES users(id) ON DELETE CASCADE,

    role VARCHAR(30) NOT NULL DEFAULT 'member'
        CHECK (role IN ('lead', 'member', 'approver')),

    joined_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_team_memberships_team_user
        UNIQUE (team_id, user_id)
);

CREATE INDEX idx_team_memberships_user_id
    ON team_memberships (user_id);