from __future__ import annotations

from dataclasses import dataclass
from typing import Any


_EPSILON = 1e-12


@dataclass
class FillResult:
    venue: str
    market: str
    side: str
    fill_size: float
    fill_price: float
    opening_quantity: float
    closing_quantity: float
    remaining_quantity: float
    average_entry: float | None
    gross_realized_pnl: float
    realized_pnl: float
    unrealized_pnl: float
    fees: float
    funding: float
    slippage: float
    closed: bool
    flipped: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "venue": self.venue,
            "market": self.market,
            "side": self.side,
            "fill_size": self.fill_size,
            "fill_price": self.fill_price,
            "opening_quantity": self.opening_quantity,
            "closing_quantity": self.closing_quantity,
            "remaining_quantity": self.remaining_quantity,
            "average_entry": self.average_entry,
            "gross_realized_pnl": self.gross_realized_pnl,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "fees": self.fees,
            "funding": self.funding,
            "slippage": self.slippage,
            "closed": self.closed,
            "flipped": self.flipped,
        }


class PositionLedger:
    """Deterministic fill accounting shared by paper/replay/backtest paths.

    Position size is signed: positive = long, negative = short.
    Fees and slippage are treated as non-negative costs. Funding is signed:
    positive values are credits, negative values are debits.
    """

    def __init__(self) -> None:
        self._positions: dict[str, dict[str, Any]] = {}
        self._gross_realized_pnl = 0.0
        self._realized_pnl = 0.0
        self._fees = 0.0
        self._funding = 0.0
        self._slippage = 0.0

    @staticmethod
    def _key(venue: str, market: str) -> str:
        return f"{venue}:{market}"

    @staticmethod
    def _signed_fill(side: str, size: float) -> float:
        normalized = side.lower().strip()
        if normalized not in ("buy", "sell"):
            raise ValueError(f"Unsupported side '{side}'")
        if size <= 0:
            raise ValueError("Fill size must be greater than zero")
        return size if normalized == "buy" else -size

    @staticmethod
    def _unrealized(size: float, entry_price: float, mark_price: float) -> float:
        if abs(size) < _EPSILON:
            return 0.0
        return size * (mark_price - entry_price)

    def apply_fill(
        self,
        *,
        venue: str,
        market: str,
        side: str,
        size: float,
        price: float,
        fee: float = 0.0,
        funding: float = 0.0,
        slippage: float = 0.0,
    ) -> dict[str, Any]:
        if price <= 0:
            raise ValueError("Fill price must be greater than zero")
        if fee < 0:
            raise ValueError("Fee must be non-negative")
        if slippage < 0:
            raise ValueError("Slippage must be non-negative")

        signed_fill = self._signed_fill(side, float(size))
        fill_size = abs(signed_fill)
        key = self._key(venue, market)
        existing = self._positions.get(key)

        opening_quantity = 0.0
        closing_quantity = 0.0
        gross_realized = 0.0
        flipped = False

        if existing is None:
            new_size = signed_fill
            new_entry = float(price)
            opening_quantity = fill_size
            cumulative_gross_realized = 0.0
            cumulative_realized = 0.0
            cumulative_fees = 0.0
            cumulative_funding = 0.0
            cumulative_slippage = 0.0
        else:
            old_size = float(existing["size"])
            old_entry = float(existing["entry_price"])
            same_direction = (old_size > 0 and signed_fill > 0) or (old_size < 0 and signed_fill < 0)

            cumulative_gross_realized = float(existing.get("gross_realized_pnl", 0.0))
            cumulative_realized = float(existing.get("realized_pnl", 0.0))
            cumulative_fees = float(existing.get("fees", 0.0))
            cumulative_funding = float(existing.get("funding", 0.0))
            cumulative_slippage = float(existing.get("slippage", 0.0))

            if same_direction:
                opening_quantity = fill_size
                new_size = old_size + signed_fill
                new_entry = (
                    abs(old_size) * old_entry + fill_size * float(price)
                ) / abs(new_size)
            else:
                closing_quantity = min(abs(old_size), fill_size)
                if old_size > 0:
                    gross_realized = closing_quantity * (float(price) - old_entry)
                else:
                    gross_realized = closing_quantity * (old_entry - float(price))

                residual_fill = fill_size - closing_quantity
                new_size = old_size + signed_fill

                if residual_fill <= _EPSILON:
                    new_entry = old_entry if abs(new_size) > _EPSILON else 0.0
                else:
                    flipped = True
                    opening_quantity = residual_fill
                    new_entry = float(price)

        fill_net_realized = gross_realized - float(fee) - float(slippage) + float(funding)
        self._gross_realized_pnl += gross_realized
        self._realized_pnl += fill_net_realized
        self._fees += float(fee)
        self._funding += float(funding)
        self._slippage += float(slippage)

        cumulative_gross_realized += gross_realized
        cumulative_realized += fill_net_realized
        cumulative_fees += float(fee)
        cumulative_funding += float(funding)
        cumulative_slippage += float(slippage)

        if abs(new_size) <= _EPSILON:
            self._positions.pop(key, None)
            unrealized = 0.0
            remaining_quantity = 0.0
            average_entry = None
            closed = True
        else:
            mark_price = float(price)
            unrealized = self._unrealized(new_size, new_entry, mark_price)
            self._positions[key] = {
                "venue": venue,
                "market": market,
                "size": new_size,
                "entry_price": new_entry,
                "mark_price": mark_price,
                "unrealized_pnl": unrealized,
                "pnl": unrealized,
                "gross_realized_pnl": cumulative_gross_realized,
                "realized_pnl": cumulative_realized,
                "fees": cumulative_fees,
                "funding": cumulative_funding,
                "slippage": cumulative_slippage,
                "margin": float(existing.get("margin", 0.0)) if existing else 0.0,
            }
            remaining_quantity = new_size
            average_entry = new_entry
            closed = False

        return FillResult(
            venue=venue,
            market=market,
            side=side.lower().strip(),
            fill_size=fill_size,
            fill_price=float(price),
            opening_quantity=opening_quantity,
            closing_quantity=closing_quantity,
            remaining_quantity=remaining_quantity,
            average_entry=average_entry,
            gross_realized_pnl=gross_realized,
            realized_pnl=fill_net_realized,
            unrealized_pnl=unrealized,
            fees=float(fee),
            funding=float(funding),
            slippage=float(slippage),
            closed=closed,
            flipped=flipped,
        ).as_dict()

    def apply_funding(self, venue: str, market: str, amount: float) -> dict[str, Any] | None:
        """Apply a signed funding credit/debit without changing position size."""
        key = self._key(venue, market)
        position = self._positions.get(key)
        if position is None:
            return None
        value = float(amount)
        self._funding += value
        self._realized_pnl += value
        position["funding"] = float(position.get("funding", 0.0)) + value
        position["realized_pnl"] = float(position.get("realized_pnl", 0.0)) + value
        return dict(position)

    def mark_to_market(self, venue: str, market: str, mark_price: float) -> dict[str, Any] | None:
        if mark_price <= 0:
            raise ValueError("Mark price must be greater than zero")
        key = self._key(venue, market)
        position = self._positions.get(key)
        if position is None:
            return None
        position["mark_price"] = float(mark_price)
        position["unrealized_pnl"] = self._unrealized(
            float(position["size"]),
            float(position["entry_price"]),
            float(mark_price),
        )
        position["pnl"] = position["unrealized_pnl"]
        return dict(position)

    def get_positions(self) -> list[dict[str, Any]]:
        return [dict(position) for position in self._positions.values()]

    def get_account_totals(self) -> dict[str, float]:
        positions = self.get_positions()
        gross_exposure = sum(
            abs(float(p["size"]) * float(p.get("mark_price") or p["entry_price"]))
            for p in positions
        )
        net_exposure = sum(
            float(p["size"]) * float(p.get("mark_price") or p["entry_price"])
            for p in positions
        )
        unrealized_pnl = sum(float(p.get("unrealized_pnl", 0.0)) for p in positions)
        margin_used = sum(float(p.get("margin", 0.0)) for p in positions)

        return {
            "gross_realized_pnl": self._gross_realized_pnl,
            "realized_pnl": self._realized_pnl,
            "unrealized_pnl": unrealized_pnl,
            "fees": self._fees,
            "funding": self._funding,
            "slippage": self._slippage,
            "gross_exposure": gross_exposure,
            "net_exposure": net_exposure,
            "margin_used": margin_used,
        }
