"""Shared exceptions for user database operations."""


class UserOperationError(Exception):
    """Base exception for user-related operations."""


class UserAlreadyExistsError(UserOperationError):
    """The supplied email is already registered."""


class InvalidUserRecordError(UserOperationError):
    """The database rejected the user data as invalid."""


class UserDatabaseError(UserOperationError):
    """A database operation failed."""


class UserCreationError(UserDatabaseError):
    """A user could not be created."""