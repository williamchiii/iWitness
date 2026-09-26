import psycopg
from collections.abc import Iterator

try:
    from .config import settings
except ImportError:
    # Supports ``uvicorn main:app`` when launched from the server directory.
    from config import settings

DATABASE_URL = settings.database_url


def connect() -> psycopg.Connection:
    """Open a new connection to DATABASE_URL.

    Used as a context manager (as every call site does), it commits on a
    clean exit and rolls back on an exception.
    """

    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured")
    return psycopg.connect(DATABASE_URL, connect_timeout=10)


def get_db() -> Iterator[psycopg.Connection]:
    """Provide one transaction-scoped connection for a request."""

    with connect() as connection:
        yield connection
