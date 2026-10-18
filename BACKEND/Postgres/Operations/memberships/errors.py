"""Exceptions raised by team membership database operations."""


class MembershipAlreadyExistsError(Exception):
    """The user is already a member of this team."""


class InvalidMembershipRecordError(Exception):
    """Membership data violates a database constraint."""


class MembershipRelatedRecordNotFoundError(Exception):
    """The referenced team or user does not exist."""


class MembershipDatabaseError(Exception):
    """A membership database operation failed."""