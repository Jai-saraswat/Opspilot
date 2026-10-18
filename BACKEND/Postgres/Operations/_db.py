"""Shared database connection and logging helpers for Operations."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

import psycopg

from BACKEND.Postgres.gateway import get_connection


@contextmanager
def connection_scope(
    connection: psycopg.Connection | None = None,
) -> Iterator[psycopg.Connection]:
    """Use a supplied connection or manage a new connection.

    If a connection is supplied, the caller owns the transaction.

    Otherwise, obtain a connection through the PostgreSQL gateway.
    The connection context commits on success, rolls back on failure,
    and closes the connection when the context exits.
    """
    if connection is not None:
        yield connection
        return

    with get_connection() as managed_connection:
        yield managed_connection


def log_database_failure(
    logger: logging.Logger,
    operation: str,
    error: Exception,
) -> None:
    """Log safe diagnostic information without sensitive query parameters."""
    sqlstate = (
        error.sqlstate
        if isinstance(error, psycopg.Error)
        else None
    )

    logger.error(
        "Database operation '%s' failed (SQLSTATE=%s).",
        operation,
        sqlstate or "unavailable",
    )