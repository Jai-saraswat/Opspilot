"""Exceptions raised by activity-history database operations."""


class InvalidActivityRecordError(Exception):
    """Activity data violates a database constraint."""


class ActivityRelatedRecordNotFoundError(Exception):
    """A referenced work item or actor does not exist."""


class ActivityDatabaseError(Exception):
    """An activity-history database operation failed."""