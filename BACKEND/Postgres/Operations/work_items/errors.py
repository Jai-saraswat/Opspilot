"""Exceptions raised by work-item database operations."""


class InvalidWorkItemRecordError(Exception):
    """Work-item data violates a database constraint."""


class WorkItemRelatedRecordNotFoundError(Exception):
    """A referenced user or team does not exist."""


class WorkItemDatabaseError(Exception):
    """A work-item database operation failed."""