import os
import logging
import threading
from pathlib import Path

import psycopg2
import psycopg2.extras
import psycopg2.pool

logger = logging.getLogger(__name__)

_pool: psycopg2.pool.ThreadedConnectionPool | None = None
_pool_init_lock = threading.Lock()

MIGRATIONS_PATH = Path(__file__).parent / "migrations.sql"
_MIGRATION_ADVISORY_LOCK_ID = 824873219


def _get_database_url() -> str:
    return os.environ.get("DATABASE_URL", "")


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _pool

    if _pool is not None and not _pool.closed:
        return _pool

    with _pool_init_lock:
        if _pool is not None and not _pool.closed:
            return _pool

        url = _get_database_url()
        if not url:
            raise RuntimeError("DATABASE_URL not set")

        _pool = psycopg2.pool.ThreadedConnectionPool(1, 10, url)
        logger.info("Thread-safe database connection pool created")
        return _pool


def get_connection():
    pool = _get_pool()
    conn = pool.getconn()
    conn.autocommit = True
    return conn


def release_connection(conn) -> None:
    """Return a connection without ever resurrecting a closed pool."""
    pool = _pool
    if pool is not None and not pool.closed:
        try:
            pool.putconn(conn)
            return
        except Exception:
            logger.warning("Failed to return database connection to pool", exc_info=True)

    try:
        conn.close()
    except Exception:
        pass


def close_pool() -> None:
    """Close all pooled PostgreSQL connections. Safe to call more than once."""
    global _pool

    with _pool_init_lock:
        pool = _pool
        _pool = None
        if pool is None or pool.closed:
            return
        try:
            pool.closeall()
            logger.info("Database connection pool closed")
        except Exception:
            logger.warning("Failed to close database connection pool cleanly", exc_info=True)


def execute_query(sql: str, params: tuple | list | None = None) -> list[dict]:
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            if cur.description:
                rows = cur.fetchall()
                return [dict(row) for row in rows]
            return []
    finally:
        release_connection(conn)


def execute_write(sql: str, params: tuple | list | None = None) -> int:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.rowcount
    finally:
        release_connection(conn)


def execute_returning(sql: str, params: tuple | list | None = None) -> dict | None:
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            if cur.description:
                row = cur.fetchone()
                return dict(row) if row else None
            return None
    finally:
        release_connection(conn)


def init_db() -> None:
    if not MIGRATIONS_PATH.exists():
        logger.warning("Migrations file not found at %s", MIGRATIONS_PATH)
        return

    sql = MIGRATIONS_PATH.read_text()
    conn = get_connection()
    lock_acquired = False

    try:
        with conn.cursor() as cur:
            # Multiple application workers can start concurrently. A session-level
            # advisory lock serializes migrations without introducing a second
            # migration framework or changing the existing migrations.sql flow.
            cur.execute("SELECT pg_advisory_lock(%s)", (_MIGRATION_ADVISORY_LOCK_ID,))
            lock_acquired = True
            cur.execute(sql)
        logger.info("Database migrations applied successfully")
    except Exception:
        logger.error("Failed to apply migrations", exc_info=True)
        raise
    finally:
        if lock_acquired:
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT pg_advisory_unlock(%s)", (_MIGRATION_ADVISORY_LOCK_ID,))
            except Exception:
                logger.warning("Failed to release database migration advisory lock", exc_info=True)
        release_connection(conn)


def check_connection() -> bool:
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            return True
        finally:
            release_connection(conn)
    except Exception:
        return False


def check_required_tables(required_tables: tuple[str, ...] | list[str]) -> tuple[bool, list[str]]:
    """Verify the small set of tables required by the live execution/audit path."""
    required = [str(name) for name in required_tables]
    if not required:
        return True, []

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = ANY(%s)",
                (required,),
            )
            present = {row[0] for row in cur.fetchall()}
    finally:
        release_connection(conn)

    missing = [name for name in required if name not in present]
    return not missing, missing
