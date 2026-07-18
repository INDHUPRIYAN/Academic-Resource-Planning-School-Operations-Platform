"""Database engine and session management.

Hardened for hosted Postgres (Render, Heroku, RDS, ...), where the provider silently
closes idle connections and occasionally restarts the instance. Without the settings
below, SQLAlchemy hands out a socket the server has already hung up on and the request
dies with:

    (psycopg2.OperationalError) server closed the connection unexpectedly

which surfaces to users as a random 500 after any quiet period. Three layers guard it:

  1. pool_pre_ping   - validate a pooled connection before use; silently replace a dead
                       one. Removes the entire stale-connection failure class.
  2. pool_recycle    - retire connections before the provider's idle cutoff (Render
                       ~5 min, so the default 280s stays safely under it).
  3. keepalives      - stop NAT/load-balancers from silently dropping idle sockets.

`db_session()` adds a bounded retry for genuinely transient connect failures (provider
restart / failover), so a blip becomes a short pause instead of an error page.
"""
import logging
import time
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import settings

log = logging.getLogger(__name__)

is_sqlite = settings.DATABASE_URL.startswith("sqlite")

if is_sqlite:
    # SQLite (tests/local): no network pool semantics apply.
    connect_args = {"check_same_thread": False}
    engine_kwargs: dict = {}
else:
    connect_args = {
        # Fail fast instead of hanging a worker forever on a dead host.
        "connect_timeout": 10,
        # Detect half-open sockets that a NAT/proxy dropped without telling us.
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 5,
        "application_name": "eduflow-api",
    }
    engine_kwargs = {
        "pool_pre_ping": settings.DB_POOL_PRE_PING,
        "pool_recycle": settings.DB_POOL_RECYCLE,
        "pool_size": settings.DB_POOL_SIZE,
        "max_overflow": settings.DB_MAX_OVERFLOW,
        "pool_timeout": settings.DB_POOL_TIMEOUT,
    }

engine = create_engine(settings.DATABASE_URL, connect_args=connect_args, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


if not is_sqlite:
    @event.listens_for(engine, "engine_connect")
    def _log_new_connection(conn, branch):  # pragma: no cover - diagnostics only
        log.debug("db: new connection checked out")


def _is_transient(exc: BaseException) -> bool:
    """Connection-level failures worth retrying. A constraint violation or bad SQL is
    NOT transient and must surface immediately rather than be retried."""
    if isinstance(exc, OperationalError):
        return True
    if isinstance(exc, DBAPIError):
        return bool(getattr(exc, "connection_invalidated", False))
    return False


def _new_session_with_retry():
    """Open a session, retrying only transient connect failures with backoff.

    Always returns a live session or raises: the final attempt re-raises rather than
    falling out of the loop, so there is no path that yields None.
    """
    attempts = max(1, settings.DB_CONNECT_RETRIES)
    for attempt in range(1, attempts + 1):
        db = SessionLocal()
        try:
            # Force a real connection now so a dead host fails here (retryable) rather
            # than midway through a request handler.
            db.connection()
            return db
        except Exception as exc:  # noqa: BLE001 - re-raised on the last attempt
            db.close()
            if not _is_transient(exc) or attempt == attempts:
                raise
            wait = settings.DB_CONNECT_RETRY_BACKOFF * (2 ** (attempt - 1))
            log.warning("db: transient connect failure (attempt %d/%d), retrying in %.1fs: %s",
                        attempt, attempts, wait, str(exc).splitlines()[0][:120])
            time.sleep(wait)


def get_db():
    """FastAPI dependency. Rolls back on error so a failed request can never leak a
    dirty session back into the pool."""
    db = _new_session_with_retry()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def db_session():
    """Same guarantees as get_db() for scripts, seeds and background jobs."""
    db = _new_session_with_retry()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def healthcheck() -> bool:
    """True if the database answers. Used by /health so a load balancer can tell a
    live-but-DB-less instance apart from a healthy one."""
    from sqlalchemy import text
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001
        log.error("db: healthcheck failed: %s", str(exc).splitlines()[0][:160])
        return False
