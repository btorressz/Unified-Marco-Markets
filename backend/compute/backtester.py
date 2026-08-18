from __future__ import annotations

import logging
import math
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.core.position_ledger import PositionLedger

logger = logging.getLogger(__name__)

_RANDOM_SEED = 42
_EPSILON = 1e-12


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _parse_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        raw = str(value or "").strip()
        if not raw:
            raise ValueError("Historical observation is missing a timestamp")
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _simulate_price_path(
    start_price: float,
    n_steps: int,
    daily_vol: float,
    drift: float,
    seed: int = _RANDOM_SEED,
) -> list[float]:
    rng = random.Random(seed)
    prices = [start_price]
    step_vol = daily_vol / math.sqrt(252)
    step_drift = drift / 252
    for _ in range(n_steps):
        z = rng.gauss(0, 1)
        ret = step_drift + step_vol * z
        prices.append(prices[-1] * (1.0 + ret))
    return prices


def _compute_sharpe(returns: list[float], risk_free_rate: float = 0.04) -> float:
    if len(returns) < 2:
        return 0.0
    n = len(returns)
    mean_r = sum(returns) / n
    variance = sum((r - mean_r) ** 2 for r in returns) / (n - 1)
    std_r = math.sqrt(variance) if variance > 0 else 0.0
    ann_mean = mean_r * 252
    if std_r == 0:
        excess = ann_mean - risk_free_rate
        if excess > 0:
            return 999.0
        if excess < 0:
            return -999.0
        return 0.0
    ann_std = std_r * math.sqrt(252)
    return (ann_mean - risk_free_rate) / ann_std


def _compute_max_drawdown(equity_curve: list[float]) -> float:
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for val in equity_curve:
        if val > peak:
            peak = val
        dd = (peak - val) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
    return max_dd


def _compute_var_cvar(returns: list[float], confidence: float = 0.95) -> tuple[float, float]:
    if not returns:
        return 0.0, 0.0
    sorted_r = sorted(returns)
    idx = int((1.0 - confidence) * len(sorted_r))
    var = -sorted_r[max(idx - 1, 0)]
    tail = sorted_r[:max(idx, 1)]
    cvar = -sum(tail) / len(tail) if tail else var
    return round(var, 6), round(cvar, 6)


def _downsample(series: list[Any], max_points: int) -> list[Any]:
    if len(series) <= max_points:
        return series
    step = len(series) / max_points
    sampled = [series[int(i * step)] for i in range(max_points)]
    if sampled[-1] != series[-1]:
        sampled.append(series[-1])
    return sampled


def _daily_equity(equity_timeline: list[dict[str, Any]]) -> list[float]:
    if not equity_timeline:
        return []
    by_day: dict[str, float] = {}
    for point in equity_timeline:
        day = _parse_ts(point["ts"]).date().isoformat()
        by_day[day] = float(point["equity"])
    return [by_day[key] for key in sorted(by_day)]


def _returns_from_equity(values: list[float]) -> list[float]:
    returns: list[float] = []
    for prev, current in zip(values, values[1:]):
        returns.append((current - prev) / prev if prev > 0 else 0.0)
    return returns


def _build_walk_forward_windows(
    equity_timeline: list[dict[str, Any]],
    *,
    train_days: int,
    test_days: int,
    step_days: int,
) -> list[dict[str, Any]]:
    if len(equity_timeline) < 2:
        return []
    first_ts = _parse_ts(equity_timeline[0]["ts"])
    last_ts = _parse_ts(equity_timeline[-1]["ts"])
    cursor = first_ts
    windows: list[dict[str, Any]] = []
    while cursor + timedelta(days=train_days + test_days) <= last_ts:
        train_end = cursor + timedelta(days=train_days)
        test_end = train_end + timedelta(days=test_days)
        test_points = [
            p for p in equity_timeline
            if train_end <= _parse_ts(p["ts"]) <= test_end
        ]
        if len(test_points) >= 2:
            values = [float(p["equity"]) for p in test_points]
            start_equity = values[0]
            end_equity = values[-1]
            windows.append({
                "train_start": cursor.isoformat(),
                "train_end": train_end.isoformat(),
                "test_start": train_end.isoformat(),
                "test_end": test_end.isoformat(),
                "test_return_pct": round(
                    ((end_equity - start_equity) / start_equity * 100.0)
                    if start_equity > 0 else 0.0,
                    4,
                ),
                "test_max_drawdown_pct": round(_compute_max_drawdown(values) * 100.0, 4),
                "observation_count": len(test_points),
            })
        cursor += timedelta(days=step_days)
    return windows


def _run_synthetic_backtest(config: dict[str, Any]) -> dict[str, Any]:
    """Preserve the original seeded research/demo backtester."""
    window_days = int(_clamp(float(config.get("window_days", 30)), 1, 365))
    initial_capital = float(config.get("initial_capital", 10000.0))
    fee_bps = float(config.get("fee_bps", 10.0))
    slippage_bps = float(config.get("slippage_bps", 5.0))
    funding_rate_daily = float(config.get("funding_rate_daily", 0.0001))
    trade_frequency_days = float(config.get("trade_frequency_days", 1.0))
    strategy = str(config.get("strategy", "momentum"))
    venue = str(config.get("venue", "hyperliquid"))
    start_price = float(config.get("start_price", 150.0))
    daily_vol = float(config.get("daily_vol", 0.04))
    drift = float(config.get("drift", 0.10))

    prices = _simulate_price_path(start_price, window_days, daily_vol, drift)
    cost_per_trade = (fee_bps + slippage_bps) / 10000.0
    trade_interval = max(int(trade_frequency_days), 1)
    positions: list[dict[str, Any]] = []
    equity_curve = [initial_capital]
    capital = initial_capital
    holding = 0.0
    entry_price = 0.0
    wins = 0
    losses = 0
    total_trades = 0
    total_slippage = 0.0
    per_strategy_pnl: dict[str, float] = {"momentum": 0.0, "carry": 0.0, "funding": 0.0}
    daily_returns: list[float] = []

    for i in range(1, window_days + 1):
        price = prices[i]
        prev_price = prices[i - 1]
        if holding != 0.0:
            carry_pnl = holding * prev_price * funding_rate_daily
            capital += carry_pnl
            per_strategy_pnl["funding"] += carry_pnl

        if i % trade_interval == 0:
            if holding != 0.0:
                trade_cost = abs(holding) * price * cost_per_trade
                trade_pnl = holding * (price - entry_price) - trade_cost
                capital += trade_pnl
                total_slippage += abs(holding) * price * (slippage_bps / 10000.0)
                wins += int(trade_pnl > 0)
                losses += int(trade_pnl <= 0)
                total_trades += 1
                per_strategy_pnl["momentum"] += trade_pnl
                positions.append({
                    "entry": round(entry_price, 4),
                    "exit": round(price, 4),
                    "pnl": round(trade_pnl, 4),
                    "side": "long" if holding > 0 else "short",
                    "day": i,
                })

            if strategy == "momentum":
                if price > prev_price * 1.005:
                    holding = capital / price * 0.5
                    entry_price = price
                elif price < prev_price * 0.995:
                    holding = -(capital / price * 0.5)
                    entry_price = price
                else:
                    holding = 0.0
                    entry_price = 0.0
            elif strategy == "carry_arb":
                if funding_rate_daily > 0:
                    holding = -(capital / price * 0.4)
                    entry_price = price
                else:
                    holding = capital / price * 0.4
                    entry_price = price
            else:
                holding = capital / price * 0.3
                entry_price = price

        daily_return = (capital - equity_curve[-1]) / equity_curve[-1] if equity_curve[-1] > 0 else 0.0
        daily_returns.append(daily_return)
        equity_curve.append(capital)

    if holding != 0.0 and prices:
        final_price = prices[-1]
        trade_cost = abs(holding) * final_price * cost_per_trade
        trade_pnl = holding * (final_price - entry_price) - trade_cost
        capital += trade_pnl
        equity_curve[-1] = capital
        total_slippage += abs(holding) * final_price * (slippage_bps / 10000.0)
        wins += int(trade_pnl > 0)
        losses += int(trade_pnl <= 0)
        total_trades += 1

    total_return = (capital - initial_capital) / initial_capital if initial_capital > 0 else 0.0
    sharpe = _compute_sharpe(daily_returns)
    max_dd = _compute_max_drawdown(equity_curve)
    win_rate = wins / total_trades if total_trades > 0 else 0.0
    avg_slippage_bps = (total_slippage / initial_capital * 10000) / total_trades if total_trades > 0 else 0.0
    var_95, cvar_95 = _compute_var_cvar(daily_returns)

    return {
        "mode": "synthetic",
        "data_mode": "synthetic_research_simulation",
        "total_return": round(total_return, 6),
        "total_return_pct": round(total_return * 100, 3),
        "final_capital": round(capital, 4),
        "sharpe_ratio": round(sharpe, 4),
        "max_drawdown": round(max_dd, 6),
        "max_drawdown_pct": round(max_dd * 100, 3),
        "win_rate": round(win_rate, 4),
        "trade_count": total_trades,
        "fill_count": total_trades,
        "avg_slippage_bps": round(avg_slippage_bps, 2),
        "var_95": round(var_95, 6),
        "cvar_95": round(cvar_95, 6),
        "equity_curve": [round(v, 2) for v in _downsample(equity_curve, 50)],
        "per_strategy_pnl": {k: round(v, 4) for k, v in per_strategy_pnl.items()},
        "data_manifest": {"synthetic_price_steps": len(prices)},
        "config": {
            "mode": "synthetic",
            "window_days": window_days,
            "initial_capital": initial_capital,
            "strategy": strategy,
            "venue": venue,
            "fee_bps": fee_bps,
            "slippage_bps": slippage_bps,
            "funding_rate_daily": funding_rate_daily,
        },
        "warnings": ["Synthetic mode uses a seeded simulated price path; it is not historical market replay."],
        "ts": datetime.now(timezone.utc).isoformat(),
    }


def _timeline(bundle: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    priorities = {
        "index": 10,
        "regime": 20,
        "stablecoin": 30,
        "funding": 40,
        "event": 50,
        "market": 60,
        "recorded_fill": 70,
    }
    mapping = {
        "index_history": "index",
        "regime_snapshots": "regime",
        "stablecoin_ticks": "stablecoin",
        "funding_ticks": "funding",
        "events": "event",
        "market_ticks": "market",
        "fills": "recorded_fill",
    }
    timeline: list[dict[str, Any]] = []
    for source_name, kind in mapping.items():
        for row in bundle.get(source_name, []):
            ts_key = "ts"
            try:
                ts = _parse_ts(row.get(ts_key))
            except Exception:
                continue
            timeline.append({
                "ts": ts,
                "kind": kind,
                "priority": priorities[kind],
                "id": str(row.get("id", "")),
                "data": row,
            })
    timeline.sort(key=lambda item: (item["ts"], item["priority"], item["id"]))
    return timeline


def _position_for(ledger: PositionLedger, venue: str, market: str) -> dict[str, Any] | None:
    for position in ledger.get_positions():
        if str(position.get("venue", "")).lower() == venue.lower() and str(position.get("market", "")).upper() == market.upper():
            return position
    return None


def _historical_signal(
    strategy: str,
    *,
    price: float,
    previous_price: float | None,
    funding_rate: float,
    first_decision: bool,
) -> int:
    if strategy == "buy_hold":
        return 1 if first_decision else 0
    if strategy == "carry_arb":
        return -1 if funding_rate > 0 else 1
    if previous_price is None or previous_price <= 0:
        return 0
    if price > previous_price * 1.005:
        return 1
    if price < previous_price * 0.995:
        return -1
    return 0


def _run_historical_backtest(
    config: dict[str, Any],
    historical_data: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    initial_capital = float(config.get("initial_capital", 10000.0))
    if initial_capital <= 0:
        raise ValueError("initial_capital must be greater than zero")

    strategy = str(config.get("strategy", "momentum")).lower().strip()
    venue = str(config.get("venue", "hyperliquid")).lower().strip()
    market = str(config.get("market", "SOL-PERP")).upper().strip()
    symbol = str(config.get("symbol", "SOL_USD")).upper().strip()
    latency_ms = max(0, int(config.get("latency_ms", 250)))
    maker_fee_bps = max(0.0, float(config.get("maker_fee_bps", config.get("fee_bps", 2.0))))
    taker_fee_bps = max(0.0, float(config.get("taker_fee_bps", config.get("fee_bps", 5.0))))
    slippage_bps = max(0.0, float(config.get("slippage_bps", 3.0)))
    allocation_limit = _clamp(float(config.get("allocation_limit", 0.5)), 0.0, 1.0)
    max_gross_leverage = max(0.1, float(config.get("max_gross_leverage", 1.0)))
    decision_interval_seconds = max(0, int(config.get("decision_interval_seconds", 86400)))
    fill_model = str(config.get("fill_model", "full")).lower().strip()
    partial_fill_ratio = _clamp(float(config.get("partial_fill_ratio", 0.5)), 0.01, 1.0)
    close_at_end = bool(config.get("close_at_end", strategy != "recorded_orders"))

    market_ticks = historical_data.get("market_ticks", [])
    if not market_ticks:
        raise ValueError("No historical market_ticks found for the requested window/venue/symbol")

    ledger = PositionLedger()
    timeline = _timeline(historical_data)
    latest_price: float | None = None
    previous_decision_price: float | None = None
    latest_funding_rate = 0.0
    pending: dict[str, Any] | None = None
    last_decision_ts: datetime | None = None
    first_decision = True
    fills: list[dict[str, Any]] = []
    equity_timeline: list[dict[str, Any]] = []
    warnings: list[str] = []
    wins = 0
    losses = 0
    rejected_capital = 0

    def current_equity() -> float:
        totals = ledger.get_account_totals()
        return initial_capital + float(totals["realized_pnl"]) + float(totals["unrealized_pnl"])

    def record_equity(ts: datetime) -> None:
        totals = ledger.get_account_totals()
        equity_timeline.append({
            "ts": ts.isoformat(),
            "equity": round(initial_capital + totals["realized_pnl"] + totals["unrealized_pnl"], 8),
            "realized_pnl": round(totals["realized_pnl"], 8),
            "unrealized_pnl": round(totals["unrealized_pnl"], 8),
            "gross_exposure": round(totals["gross_exposure"], 8),
        })

    def apply_simulated_fill(order: dict[str, Any], observed_price: float, ts: datetime) -> None:
        nonlocal pending, wins, losses
        remaining = float(order["remaining_size"])
        ratio = 1.0 if fill_model == "full" else partial_fill_ratio
        fill_size = remaining if ratio >= 1.0 else min(remaining, max(remaining * ratio, 1e-12))
        if fill_size <= _EPSILON:
            pending = None
            return
        side = str(order["side"])
        signed_slip = slippage_bps / 10000.0
        fill_price = observed_price * (1.0 + signed_slip if side == "buy" else 1.0 - signed_slip)
        notional = fill_size * fill_price
        fee_bps = maker_fee_bps if str(order.get("order_type")) == "limit" else taker_fee_bps
        fee = notional * fee_bps / 10000.0
        slippage_cost = fill_size * abs(fill_price - observed_price)
        result = ledger.apply_fill(
            venue=venue,
            market=market,
            side=side,
            size=fill_size,
            price=fill_price,
            fee=fee,
            slippage=slippage_cost,
        )
        result.update({
            "ts": ts.isoformat(),
            "source": "simulated_from_historical_tick",
            "observed_price": observed_price,
            "signal_ts": order["signal_ts"].isoformat(),
            "eligible_ts": order["eligible_ts"].isoformat(),
        })
        fills.append(result)
        if float(result.get("closing_quantity", 0.0)) > 0:
            wins += int(float(result.get("realized_pnl", 0.0)) > 0)
            losses += int(float(result.get("realized_pnl", 0.0)) <= 0)
        remaining -= fill_size
        if remaining <= 1e-10:
            pending = None
        else:
            pending = {**order, "remaining_size": remaining}

    for observation in timeline:
        ts = observation["ts"]
        kind = observation["kind"]
        data = observation["data"]

        if kind == "funding":
            if str(data.get("venue", "")).lower() == venue and str(data.get("market", "")).upper() == market:
                latest_funding_rate = float(data.get("funding_rate", 0.0) or 0.0)
                position = _position_for(ledger, venue, market)
                if position is not None:
                    mark = float(position.get("mark_price") or position.get("entry_price") or 0.0)
                    amount = -float(position.get("size", 0.0)) * mark * latest_funding_rate
                    ledger.apply_funding(venue, market, amount)
                    record_equity(ts)
            continue

        if kind == "recorded_fill" and strategy == "recorded_orders":
            if str(data.get("venue", "")).lower() != venue or str(data.get("market", "")).upper() != market:
                continue
            fill_result = ledger.apply_fill(
                venue=venue,
                market=market,
                side=str(data.get("side", "buy")),
                size=float(data.get("size", 0.0) or 0.0),
                price=float(data.get("price", 0.0) or 0.0),
                fee=max(0.0, float(data.get("fee", 0.0) or 0.0)),
                funding=float(data.get("funding", 0.0) or 0.0),
                slippage=max(0.0, float(data.get("slippage", 0.0) or 0.0)),
            )
            fill_result.update({"ts": ts.isoformat(), "source": "recorded_fill"})
            fills.append(fill_result)
            if float(fill_result.get("closing_quantity", 0.0)) > 0:
                wins += int(float(fill_result.get("realized_pnl", 0.0)) > 0)
                losses += int(float(fill_result.get("realized_pnl", 0.0)) <= 0)
            record_equity(ts)
            continue

        if kind != "market":
            continue
        if str(data.get("venue", "")).lower() != venue:
            continue
        row_symbol = str(data.get("symbol", "")).upper()
        if symbol and row_symbol != symbol:
            continue
        price = float(data.get("price", 0.0) or 0.0)
        if price <= 0:
            continue

        latest_price = price
        ledger.mark_to_market(venue, market, price)

        # Existing pending decisions execute only on a market observation at or
        # after their latency timestamp. Decisions generated from this tick can
        # never fill on the same tick, which prevents same-observation look-ahead.
        if pending is not None and ts >= pending["eligible_ts"]:
            apply_simulated_fill(pending, price, ts)
            ledger.mark_to_market(venue, market, price)

        record_equity(ts)

        if strategy == "recorded_orders" or pending is not None:
            continue
        if strategy == "buy_hold" and not first_decision:
            continue
        if last_decision_ts is not None and (ts - last_decision_ts).total_seconds() < decision_interval_seconds:
            continue

        direction = _historical_signal(
            strategy,
            price=price,
            previous_price=previous_decision_price,
            funding_rate=latest_funding_rate,
            first_decision=first_decision,
        )
        previous_decision_price = price
        last_decision_ts = ts
        first_decision = False

        position = _position_for(ledger, venue, market)
        current_size = float(position.get("size", 0.0)) if position else 0.0
        equity = current_equity()
        if equity <= 0:
            warnings.append("Equity depleted; no additional positions opened.")
            continue

        if direction == 0:
            target_size = 0.0
        else:
            target_notional = min(equity * allocation_limit, equity * max_gross_leverage)
            target_size = direction * target_notional / price

        delta = target_size - current_size
        if abs(delta) <= 1e-10:
            continue
        proposed_notional = abs(delta) * price
        if proposed_notional > equity * max_gross_leverage + 1e-9:
            rejected_capital += 1
            continue

        pending = {
            "side": "buy" if delta > 0 else "sell",
            "remaining_size": abs(delta),
            "signal_ts": ts,
            "eligible_ts": ts + timedelta(milliseconds=latency_ms),
            "order_type": "market",
        }

    if not equity_timeline:
        raise ValueError("Historical window contained no matching usable market observations")

    if close_at_end and latest_price is not None:
        position = _position_for(ledger, venue, market)
        if position is not None and abs(float(position.get("size", 0.0))) > _EPSILON:
            size = abs(float(position["size"]))
            side = "sell" if float(position["size"]) > 0 else "buy"
            notional = size * latest_price
            fee = notional * taker_fee_bps / 10000.0
            slip_price = latest_price * (1.0 + slippage_bps / 10000.0 if side == "buy" else 1.0 - slippage_bps / 10000.0)
            slippage_cost = size * abs(slip_price - latest_price)
            result = ledger.apply_fill(
                venue=venue,
                market=market,
                side=side,
                size=size,
                price=slip_price,
                fee=fee,
                slippage=slippage_cost,
            )
            result.update({
                "ts": equity_timeline[-1]["ts"],
                "source": "end_of_window_close",
                "observed_price": latest_price,
            })
            fills.append(result)
            wins += int(float(result.get("realized_pnl", 0.0)) > 0)
            losses += int(float(result.get("realized_pnl", 0.0)) <= 0)
            record_equity(_parse_ts(equity_timeline[-1]["ts"]))

    totals = ledger.get_account_totals()
    final_equity = initial_capital + totals["realized_pnl"] + totals["unrealized_pnl"]
    daily_values = _daily_equity(equity_timeline)
    if not daily_values:
        daily_values = [initial_capital, final_equity]
    elif daily_values[0] != initial_capital:
        daily_values.insert(0, initial_capital)
    daily_returns = _returns_from_equity(daily_values)
    total_return = (final_equity - initial_capital) / initial_capital
    max_dd = _compute_max_drawdown(daily_values)
    sharpe = _compute_sharpe(daily_returns)
    var_95, cvar_95 = _compute_var_cvar(daily_returns)
    closing_trades = wins + losses
    win_rate = wins / closing_trades if closing_trades else 0.0
    fill_notional = sum(float(f.get("fill_size", 0.0)) * float(f.get("fill_price", 0.0)) for f in fills)
    avg_slippage_bps = (
        float(totals["slippage"]) / fill_notional * 10000.0
        if fill_notional > 0 else 0.0
    )

    data_manifest = {name: len(rows) for name, rows in historical_data.items()}
    data_manifest["usable_market_observations"] = sum(
        1 for row in market_ticks
        if str(row.get("venue", "")).lower() == venue
        and (not symbol or str(row.get("symbol", "")).upper() == symbol)
    )

    walk_forward_windows: list[dict[str, Any]] = []
    if bool(config.get("walk_forward", False)):
        walk_forward_windows = _build_walk_forward_windows(
            equity_timeline,
            train_days=max(1, int(config.get("train_window_days", 30))),
            test_days=max(1, int(config.get("test_window_days", 7))),
            step_days=max(1, int(config.get("step_days", 7))),
        )

    return {
        "mode": "historical",
        "data_mode": "historical_event_time",
        "total_return": round(total_return, 6),
        "total_return_pct": round(total_return * 100.0, 3),
        "final_capital": round(final_equity, 4),
        "sharpe_ratio": round(sharpe, 4),
        "max_drawdown": round(max_dd, 6),
        "max_drawdown_pct": round(max_dd * 100.0, 3),
        "win_rate": round(win_rate, 4),
        "trade_count": closing_trades,
        "fill_count": len(fills),
        "avg_slippage_bps": round(avg_slippage_bps, 2),
        "var_95": round(var_95, 6),
        "cvar_95": round(cvar_95, 6),
        "fees_paid": round(float(totals["fees"]), 6),
        "funding_pnl": round(float(totals["funding"]), 6),
        "slippage_cost": round(float(totals["slippage"]), 6),
        "realized_pnl": round(float(totals["realized_pnl"]), 6),
        "unrealized_pnl": round(float(totals["unrealized_pnl"]), 6),
        "equity_curve": [round(float(p["equity"]), 2) for p in _downsample(equity_timeline, 80)],
        "equity_timeline": _downsample(equity_timeline, 200),
        "fills": _downsample(fills, 200),
        "per_strategy_pnl": {
            strategy: round(float(totals["realized_pnl"]) + float(totals["unrealized_pnl"]), 4),
            "funding": round(float(totals["funding"]), 4),
        },
        "walk_forward_windows": walk_forward_windows,
        "data_manifest": data_manifest,
        "look_ahead_guard": {
            "enabled": True,
            "rule": "decisions only use observations at or before signal time; simulated fills require a later eligible market tick",
        },
        "capital_constraints": {
            "allocation_limit": allocation_limit,
            "max_gross_leverage": max_gross_leverage,
            "rejected_orders": rejected_capital,
        },
        "config": {
            **config,
            "mode": "historical",
            "strategy": strategy,
            "venue": venue,
            "market": market,
            "symbol": symbol,
            "initial_capital": initial_capital,
            "latency_ms": latency_ms,
            "maker_fee_bps": maker_fee_bps,
            "taker_fee_bps": taker_fee_bps,
            "slippage_bps": slippage_bps,
            "fill_model": fill_model,
        },
        "warnings": warnings,
        "ts": datetime.now(timezone.utc).isoformat(),
    }


def run_backtest(
    config: dict[str, Any] | None = None,
    *,
    historical_data: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    config = dict(config or {})
    mode = str(config.get("mode", "synthetic")).lower().strip()
    if mode == "synthetic":
        return _run_synthetic_backtest(config)
    if mode != "historical":
        raise ValueError("mode must be 'synthetic' or 'historical'")
    if historical_data is None:
        raise ValueError("historical_data is required when mode='historical'")
    return _run_historical_backtest(config, historical_data)
