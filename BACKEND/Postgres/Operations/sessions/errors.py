"""Exceptions raised by login-session database operations."""


class InvalidSessionRecordError(Exception):
    """The session data violates a database constraint."""


class SessionUserNotFoundError(Exception):
    """The referenced user does not exist."""


class SessionDatabaseError(Exception):
    """A login-session database operation failed."""