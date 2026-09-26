from typing import Generator

import psycopg

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


def get_db() -> Generator[psycopg.Connection, None, None]:
    """FastAPI dependency yielding a connection scoped to one handler call.

    Always inject with ``Depends(get_db, scope="function")``. FastAPI's
    default scope for a generator dependency is ``"request"``, which keeps
    the connection open until after the response is sent — for a
    ``FileResponse``/streaming route that means holding it open for the
    whole transfer.
    """

    with connect() as connection:
        yield connection
