"""Exceptions raised by team database operations."""


class TeamAlreadyExistsError(Exception):
    """A team with the same name already exists."""


class InvalidTeamRecordError(Exception):
    """The supplied team data violates a database constraint."""


class TeamCreatorNotFoundError(Exception):
    """The user referenced as the team creator does not exist."""


class TeamInUseError(Exception):
    """The team cannot be deleted because work items reference it."""


class TeamDatabaseError(Exception):
    """A database operation on teams failed."""