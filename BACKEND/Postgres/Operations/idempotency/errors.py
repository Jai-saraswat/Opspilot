"""Exceptions raised by idempotency database operations."""


class InvalidIdempotencyRecordError(Exception):
    """The idempotency record data is invalid."""


class IdempotencyKeyReuseError(Exception):
    """The same key was used for a different request payload."""


class IdempotencyRecordNotFoundError(Exception):
    """The requested idempotency record does not exist."""


class IdempotencyRecordExpiredError(Exception):
    """The idempotency record has expired."""


class IdempotencyAlreadyCompletedError(Exception):
    """The idempotency record already contains a saved response."""


class IdempotencyDatabaseError(Exception):
    """An idempotency database operation failed."""