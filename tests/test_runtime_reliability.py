from pathlib import Path

import backend.data.db as db


class _FakeConnection:
    def __init__(self):
        self.autocommit = False
        self.closed = False
        self.executed: list[tuple[str, object]] = []

    def cursor(self, *args, **kwargs):
        return _FakeCursor(self)

    def close(self):
        self.closed = True


class _FakeCursor:
    def __init__(self, conn: _FakeConnection):
        self.conn = conn
        self.description = None
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.conn.executed.append((sql, params))


class _FakePool:
    def __init__(self, connection=None):
        self.closed = False
        self.connection = connection or _FakeConnection()
        self.get_count = 0
        self.put_count = 0
        self.closeall_count = 0

    def getconn(self):
        self.get_count += 1
        return self.connection

    def putconn(self, conn):
        assert conn is self.connection
        self.put_count += 1

    def closeall(self):
        self.closeall_count += 1
        self.closed = True


def test_database_pool_uses_threaded_connection_pool(monkeypatch):
    created = []

    def make_pool(minconn, maxconn, url):
        created.append((minconn, maxconn, url))
        return _FakePool()

    monkeypatch.setenv("DATABASE_URL", "postgresql://example/test")
    monkeypatch.setattr(db.psycopg2.pool, "ThreadedConnectionPool", make_pool)
    monkeypatch.setattr(db, "_pool", None)

    first = db._get_pool()
    second = db._get_pool()

    assert first is second
    assert created == [(1, 10, "postgresql://example/test")]

    db.close_pool()


def test_get_and_release_connection_reuse_existing_pool(monkeypatch):
    pool = _FakePool()
    monkeypatch.setattr(db, "_pool", pool)

    conn = db.get_connection()
    assert conn.autocommit is True

    db.release_connection(conn)

    assert pool.get_count == 1
    assert pool.put_count == 1
    assert conn.closed is False


def test_release_after_pool_shutdown_closes_connection_without_recreating_pool(monkeypatch):
    conn = _FakeConnection()
    monkeypatch.setattr(db, "_pool", None)

    db.release_connection(conn)

    assert conn.closed is True
    assert db._pool is None


def test_close_pool_is_idempotent(monkeypatch):
    pool = _FakePool()
    monkeypatch.setattr(db, "_pool", pool)

    db.close_pool()
    db.close_pool()

    assert pool.closeall_count == 1
    assert db._pool is None


def test_init_db_serializes_migrations_with_advisory_lock(monkeypatch, tmp_path):
    migration = tmp_path / "migrations.sql"
    migration.write_text("SELECT 42;")
    conn = _FakeConnection()
    released = []

    monkeypatch.setattr(db, "MIGRATIONS_PATH", migration)
    monkeypatch.setattr(db, "get_connection", lambda: conn)
    monkeypatch.setattr(db, "release_connection", lambda c: released.append(c))

    db.init_db()

    statements = [sql for sql, _params in conn.executed]
    assert statements[0] == "SELECT pg_advisory_lock(%s)"
    assert "SELECT 42;" in statements
    assert statements[-1] == "SELECT pg_advisory_unlock(%s)"
    assert released == [conn]


def test_main_does_not_launch_redis_and_closes_database_pool():
    source = (Path(__file__).parents[1] / "main.py").read_text()

    assert "redis-server" not in source
    assert "subprocess" not in source
    assert "shutil.which" not in source
    assert "close_pool" in source
    assert "finally:" in source
    assert "scheduler.stop()" in source
    assert "close_pool()" in source


def test_runtime_reliability_scope_does_not_add_container_or_orchestration_files():
    root = Path(__file__).parents[1]

    assert not (root / "docker-compose.yml").exists()
    assert not (root / "docker-compose.yaml").exists()
    assert not (root / "kubernetes").exists()
    assert not (root / "k8s").exists()
