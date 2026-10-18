-- Roles
CREATE TABLE roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    name VARCHAR(50) NOT NULL,
    scope VARCHAR(20) NOT NULL
        CHECK (scope IN ('system', 'team')),

    description TEXT,
    is_system_role BOOLEAN NOT NULL DEFAULT FALSE,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_roles_scope_name UNIQUE (scope, name)
);

-- Permissions
CREATE TABLE permissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    permission_key VARCHAR(100) NOT NULL UNIQUE,
    description TEXT NOT NULL
);

-- Role Permissions
CREATE TABLE role_permissions (
    role_id UUID NOT NULL
        REFERENCES roles(id) ON DELETE CASCADE,

    permission_id UUID NOT NULL
        REFERENCES permissions(id) ON DELETE CASCADE,

    PRIMARY KEY (role_id, permission_id)
);

-- System Roles Assigned to Users
CREATE TABLE user_roles (
    user_id UUID NOT NULL
        REFERENCES users(id) ON DELETE CASCADE,

    role_id UUID NOT NULL
        REFERENCES roles(id) ON DELETE CASCADE,

    assigned_by UUID
        REFERENCES users(id) ON DELETE SET NULL,

    assigned_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (user_id, role_id)
);

-- Individual Permission Overrides
CREATE TABLE user_permission_overrides (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    user_id UUID NOT NULL
        REFERENCES users(id) ON DELETE CASCADE,

    permission_id UUID NOT NULL
        REFERENCES permissions(id) ON DELETE CASCADE,

    team_id UUID
        REFERENCES teams(id) ON DELETE CASCADE,

    effect VARCHAR(10) NOT NULL
        CHECK (effect IN ('allow', 'deny')),

    assigned_by UUID
        REFERENCES users(id) ON DELETE SET NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_user_permission_global
        UNIQUE NULLS NOT DISTINCT (user_id, permission_id, team_id)
);

CREATE INDEX idx_user_roles_role_id
    ON user_roles (role_id);

CREATE INDEX idx_role_permissions_permission_id
    ON role_permissions (permission_id);

CREATE INDEX idx_user_permission_overrides_lookup
    ON user_permission_overrides (user_id, team_id, permission_id);