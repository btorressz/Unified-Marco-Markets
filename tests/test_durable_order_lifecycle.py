from pathlib import Path

from backend.core.event_bus import EventType
from backend.data.repositories.orders_repo import OrdersRepository
from backend.data.repositories.positions_repo import PositionsRepository


def test_order_lifecycle_event_types_are_complete_and_compatible():
    expected = {
        "ORDER_INTENT_CREATED",
        "ORDER_RISK_APPROVED",
        "ORDER_SUBMITTED",
        "ORDER_ACKNOWLEDGED",
        "ORDER_OPEN",
        "ORDER_PARTIALLY_FILLED",
        "ORDER_FILLED",
        "ORDER_CANCEL_PENDING",
        "ORDER_CANCELLED",
        "ORDER_REJECTED",
        "ORDER_SUBMISSION_UNKNOWN",
    }
    assert expected.issubset(set(EventType.ALL))
    assert EventType.ORDER_SENT in EventType.ALL
    assert EventType.ORDER_EXECUTION_STATE_UNKNOWN in EventType.ALL


def test_migrations_define_normalized_order_lifecycle_tables():
    migration = (Path(__file__).parents[1] / "backend" / "data" / "migrations.sql").read_text()

    for table in ("order_intents", "orders", "order_events", "fills", "paper_orders"):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in migration

    assert "ALTER TABLE positions ADD COLUMN IF NOT EXISTS order_id UUID" in migration
    assert "ALTER TABLE conditional_orders ADD COLUMN IF NOT EXISTS oco_group_id UUID" in migration
    assert "ALTER TABLE conditional_orders ADD COLUMN IF NOT EXISTS trigger_key VARCHAR(200)" in migration
    assert "CREATE UNIQUE INDEX IF NOT EXISTS idx_conditional_orders_trigger_key" in migration


def test_conditional_claim_is_single_statement_atomic(monkeypatch):
    captured = {}

    def fake_returning(sql, params=None):
        captured["sql"] = sql
        captured["params"] = params
        return {"id": "11111111-1111-1111-1111-111111111111", "status": "triggering"}

    import backend.data.repositories.orders_repo as module

    monkeypatch.setattr(module, "execute_returning", fake_returning)
    repo = OrdersRepository()
    result = repo.claim_conditional_order(
        "11111111-1111-1111-1111-111111111111",
        "conditional:11111111-1111-1111-1111-111111111111",
    )

    assert result["status"] == "triggering"
    sql = " ".join(captured["sql"].split())
    assert "UPDATE conditional_orders" in sql
    assert "status = 'triggering'" in sql
    assert "AND status = 'active'" in sql
    assert "RETURNING *" in sql


def test_oco_sibling_cancellation_only_targets_active_siblings(monkeypatch):
    captured = {}

    def fake_write(sql, params=None):
        captured["sql"] = sql
        captured["params"] = params
        return 1

    import backend.data.repositories.orders_repo as module

    monkeypatch.setattr(module, "execute_write", fake_write)
    repo = OrdersRepository()
    count = repo.cancel_oco_siblings("11111111-1111-1111-1111-111111111111")

    assert count == 1
    sql = " ".join(captured["sql"].split())
    assert "target.oco_group_id = source.oco_group_id" in sql
    assert "target.id <> source.id" in sql
    assert "target.status = 'active'" in sql


def test_mark_conditional_filled_cancels_oco_only_after_fill_transition(monkeypatch):
    calls = []

    def fake_returning(sql, params=None):
        calls.append("fill_transition")
        return {"id": params[0], "status": "filled"}

    import backend.data.repositories.orders_repo as module

    monkeypatch.setattr(module, "execute_returning", fake_returning)
    repo = OrdersRepository()
    monkeypatch.setattr(repo, "cancel_oco_siblings", lambda order_id: calls.append("cancel_siblings") or 1)

    result = repo.mark_conditional_filled("11111111-1111-1111-1111-111111111111")

    assert result["status"] == "filled"
    assert calls == ["fill_transition", "cancel_siblings"]


def test_paper_trade_history_combines_normalized_and_legacy(monkeypatch):
    calls = []

    def fake_query(sql, params=None):
        calls.append(sql)
        if "FROM paper_orders" in sql:
            return [
                {
                    "id": "new-order",
                    "venue": "paper",
                    "market": "BTC-PERP",
                    "side": "buy",
                    "size": 1.0,
                    "price": 120.0,
                    "order_type": "limit",
                    "status": "filled",
                    "ts": __import__("datetime").datetime(2026, 8, 10, 12, 0, tzinfo=__import__("datetime").timezone.utc),
                }
            ]
        return [
            {
                "id": 7,
                "venue": "paper",
                "market": "ETH-PERP",
                "side": "sell",
                "size": 2.0,
                "price": 100.0,
                "order_type": "limit",
                "status": "paper_filled",
                "ts": __import__("datetime").datetime(2026, 8, 9, 12, 0, tzinfo=__import__("datetime").timezone.utc),
            }
        ]

    import backend.data.repositories.positions_repo as module

    monkeypatch.setattr(module, "execute_query", fake_query)
    repo = PositionsRepository()
    rows = repo.get_paper_trades(limit=50)

    assert len(rows) == 2
    assert rows[0]["id"] == "new-order"
    assert rows[1]["id"] == 7
    assert len(calls) == 2


def test_order_intent_uses_database_idempotency_constraint(monkeypatch):
    captured = {}

    def fake_returning(sql, params=None):
        captured["sql"] = sql
        return {"id": "11111111-1111-1111-1111-111111111111", "idempotency_key": "idem-1"}

    import backend.data.repositories.orders_repo as module

    monkeypatch.setattr(module, "execute_returning", fake_returning)
    repo = OrdersRepository()
    result = repo.create_intent(
        request_id="request-1",
        client_order_id="client-1",
        idempotency_key="idem-1",
        venue="paper",
        market="BTC-PERP",
        side="buy",
        size=1.0,
        order_type="limit",
        price=100.0,
    )

    assert result["idempotency_key"] == "idem-1"
    assert "ON CONFLICT (idempotency_key) DO NOTHING" in captured["sql"]
