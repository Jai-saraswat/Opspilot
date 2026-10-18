"""Exceptions raised by authorization database operations."""


class RoleAlreadyExistsError(Exception):
    """A role with the same name and scope already exists."""


class InvalidAuthorizationRecordError(Exception):
    """Authorization data violates a database constraint."""


class AuthorizationRelatedRecordNotFoundError(Exception):
    """A referenced user, role, permission, or team does not exist."""


class AuthorizationDatabaseError(Exception):
    """An authorization database operation failed."""