import asyncio
import json
from pathlib import Path

from backend.core.event_bus import CHANNEL, EventBus
from backend.core.redis_runtime import RedisRuntime
from backend.core.state_store import StateStore
from backend.ingest.scheduler import IngestScheduler


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.published = []

    def ping(self):
        return True

    def set(self, key, value, ex=None, nx=False):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def setex(self, key, ttl, value):
        self.values[key] = value
        return True

    def get(self, key):
        return self.values.get(key)

    def delete(self, key):
        return 1 if self.values.pop(key, None) is not None else 0

    def eval(self, script, numkeys, key, owner):
        if self.values.get(key) == owner:
            del self.values[key]
            return 1
        return 0

    def publish(self, channel, payload):
        self.published.append((channel, payload))
        return 1


class FakeRuntime:
    def __init__(self, client=None, prefix="umm:test:"):
        self.client = client
        self.key_prefix = prefix
        self.redis_url = "redis://test"
        self.failures = []
        self.published = []

    def key(self, key):
        return f"{self.key_prefix}{key}"

    def channel(self, channel):
        return self.key(channel)

    def get_client(self, ping=True):
        return self.client

    def mark_failure(self, exc, reset=False):
        self.failures.append(str(exc))

    def publish(self, channel, payload):
        if self.client is None:
            return False
        self.published.append((self.channel(channel), payload))
        return True


class FakeLeaseStore:
    def __init__(self, *, redis_available=True, token="owner"):
        self.redis_available = redis_available
        self.token = token
        self.released = []

    def get_redis(self):
        return object() if self.redis_available else None

    def claim_lease(self, name, *, ttl, owner=None):
        return self.token

    def release_lease(self, name, owner):
        self.released.append((name, owner))
        return True


def test_redis_runtime_prefix_defaults_are_backward_compatible():
    runtime = RedisRuntime(
        redis_url="redis://localhost:6379",
        key_prefix="",
        max_connections=12,
        connect_timeout_s=1.5,
        socket_timeout_s=2.5,
        health_check_interval_s=10,
    )

    assert runtime.key("risk:throttle") == "risk:throttle"
    assert runtime.channel("desk:events") == "desk:events"
    assert runtime.max_connections == 12
    kwargs = runtime._connection_kwargs()
    assert kwargs["max_connections"] == 12
    assert kwargs["socket_connect_timeout"] == 1.5
    assert kwargs["socket_timeout"] == 2.5
    assert kwargs["health_check_interval"] == 10


def test_redis_runtime_normalizes_configured_namespace():
    runtime = RedisRuntime(
        redis_url="redis://localhost:6379",
        key_prefix="umm:prod",
    )
    assert runtime.key_prefix == "umm:prod:"
    assert runtime.key("index:latest") == "umm:prod:index:latest"
    assert runtime.channel(CHANNEL) == "umm:prod:desk:events"


def test_state_store_uses_runtime_namespace_for_snapshots():
    client = FakeRedis()
    store = StateStore(runtime=FakeRuntime(client))

    assert store.set_snapshot("index:latest", {"value": 42}) is True
    assert "umm:test:index:latest" in client.values
    assert store.get_snapshot("index:latest") == {"value": 42}


def test_idempotency_claims_are_atomic_and_store_metadata():
    client = FakeRedis()
    store = StateStore(runtime=FakeRuntime(client))

    assert store.claim_idempotency(
        "request-1",
        ttl=300,
        request_id="request-1",
        owner="execution",
    ) is True
    assert store.claim_idempotency("request-1", ttl=300) is False

    value = store.get_idempotency("request-1")
    assert value["request_id"] == "request-1"
    assert value["state"] == "claimed"
    assert value["owner"] == "execution"
    assert value["created_at"]


def test_legacy_idempotency_value_still_counts_as_claimed():
    client = FakeRedis()
    runtime = FakeRuntime(client)
    store = StateStore(runtime=runtime)
    client.values[runtime.key("idem:legacy")] = "1"

    value = store.get_idempotency("legacy")
    assert value["state"] == "claimed"
    assert store.check_idempotency_key("legacy") is True


def test_distributed_lease_release_requires_owner_token():
    client = FakeRedis()
    runtime = FakeRuntime(client)
    store = StateStore(runtime=runtime)

    owner = store.claim_lease("scheduler:pyth", ttl=30, owner="worker-a")
    assert owner == "worker-a"
    assert store.claim_lease("scheduler:pyth", ttl=30, owner="worker-b") is None
    assert store.release_lease("scheduler:pyth", "worker-b") is False
    assert store.release_lease("scheduler:pyth", "worker-a") is True


def test_event_bus_publishes_through_shared_runtime():
    runtime = FakeRuntime(FakeRedis())
    bus = EventBus(redis_runtime=runtime, database_url="")

    event_id = bus.emit("TEST_EVENT", "test", {"ok": True})

    assert event_id
    assert len(runtime.published) == 1
    channel, payload = runtime.published[0]
    assert channel == "umm:test:desk:events"
    decoded = json.loads(payload)
    assert decoded["event_type"] == "TEST_EVENT"
    assert decoded["payload"] == {"ok": True}


def test_scheduler_skips_duplicate_job_when_lease_is_held():
    scheduler = object.__new__(IngestScheduler)
    scheduler.state_store = FakeLeaseStore(redis_available=True, token=None)
    calls = []

    async def job():
        calls.append("ran")

    ran = asyncio.run(scheduler._run_with_lease("pyth", job))
    assert ran is False
    assert calls == []


def test_scheduler_runs_fail_soft_when_redis_is_unavailable():
    scheduler = object.__new__(IngestScheduler)
    scheduler.state_store = FakeLeaseStore(redis_available=False, token=None)
    calls = []

    async def job():
        calls.append("ran")

    ran = asyncio.run(scheduler._run_with_lease("pyth", job))
    assert ran is True
    assert calls == ["ran"]


def test_scheduler_releases_owned_lease_after_job():
    scheduler = object.__new__(IngestScheduler)
    store = FakeLeaseStore(redis_available=True, token="worker-a")
    scheduler.state_store = store
    calls = []

    async def job():
        calls.append("ran")

    ran = asyncio.run(scheduler._run_with_lease("pyth", job))
    assert ran is True
    assert calls == ["ran"]
    assert store.released == [("scheduler:pyth", "worker-a")]


def test_websocket_uses_shared_runtime_pubsub():
    source = Path("backend/api/ws_routes.py").read_text()
    assert "get_redis_runtime" in source
    assert "create_async_pubsub" in source
    assert "close_pubsub" in source
    assert "aioredis.from_url" not in source


def test_application_closes_redis_runtime_on_shutdown():
    source = Path("main.py").read_text()
    assert "close_redis_runtime" in source
    assert "await close_redis_runtime()" in source
    assert "redis-server" not in source
