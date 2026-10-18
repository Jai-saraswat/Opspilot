"""Exceptions raised by approval database operations."""


class InvalidApprovalRecordError(Exception):
    """Approval data violates a database constraint."""


class ApprovalRelatedRecordNotFoundError(Exception):
    """A referenced user or work item does not exist."""


class ApprovalDatabaseError(Exception):
    """An approval database operation failed."""