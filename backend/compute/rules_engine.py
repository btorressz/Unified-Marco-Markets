from datetime import datetime, timezone


class RulesEngine:

    def __init__(self):
        self.rules = [
            {
                "id": "tariff_vol_reduce", "version": 1, "active": True,
                "name": "tariff_vol_reduce",
                "evaluation_type": "directional", "expected_direction": "bearish",
                "required_context": ["tariff_rate_of_change", "vol_regime"], "expected_return": None,
                "condition": self._tariff_vol_condition,
                "action_type": "reduce_exposure",
                "explanation": "Tariff index rate_of_change > 5 and vol regime is high -> reduce exposure",
            },
            {
                "id": "shock_throttle", "version": 1, "active": True,
                "name": "shock_throttle",
                "evaluation_type": "risk_control", "expected_direction": None,
                "required_context": ["shock_score"], "expected_return": None,
                "condition": self._shock_condition,
                "action_type": "enable_risk_throttle",
                "explanation": "Shock score > 2.0 -> enable risk throttle",
            },
            {
                "id": "divergence_hedge", "version": 1, "active": True,
                "name": "divergence_hedge",
                "evaluation_type": "directional", "expected_direction": "bearish",
                "required_context": ["divergence_alert_active", "funding_regime_flipped"], "expected_return": None,
                "condition": self._divergence_hedge_condition,
                "action_type": "hedge",
                "explanation": "Divergence alert active and funding regime flipped -> hedge",
            },
            {
                "id": "negative_carry_reduce", "version": 1, "active": True,
                "name": "negative_carry_reduce",
                "evaluation_type": "directional", "expected_direction": "bearish",
                "required_context": ["carry_score"], "expected_return": None,
                "condition": self._negative_carry_condition,
                "action_type": "reduce_long_perp",
                "explanation": "Carry score very negative -> reduce long perp",
            },
            {
                "id": "stable_rotation", "version": 1, "active": True,
                "name": "stable_rotation",
                "evaluation_type": "directional", "expected_direction": "bearish",
                "required_context": ["shock_score", "tariff_rate_of_change"], "expected_return": None,
                "condition": self._stable_rotation_condition,
                "action_type": "rotate_to_stables",
                "explanation": "Tariff shock high -> rotate to 80% stables, reduce beta to 0.2",
            },
        ]

    def evaluate(self, context: dict, *, as_of=None) -> list[dict]:
        actions: list[dict] = []
        for rule in self.rules:
            if rule["condition"](context):
                actions.append({
                    "rule_name": rule["name"],
                    "rule_id": rule["id"],
                    "rule_version": rule["version"],
                    "evaluation_type": rule["evaluation_type"],
                    "expected_direction": rule["expected_direction"],
                    "action_type": rule["action_type"],
                    "venue": context.get("venue", ""),
                    "market": context.get("market", ""),
                    "side": self._infer_side(rule["action_type"]),
                    "size": context.get("suggested_size", 0.0),
                    "reason": rule["explanation"],
                    "ts": (as_of or datetime.now(timezone.utc)).isoformat(),
                })
        return actions

    def evaluate_version(self, heuristic_id: str, heuristic_version: int, context: dict, *, as_of=None) -> dict:
        """Evaluate one registered rule version without falling forward to a newer rule."""
        rule = next((r for r in self.rules if r["id"] == heuristic_id and int(r["version"]) == int(heuristic_version)), None)
        if rule is None:
            raise LookupError(f"heuristic unavailable: {heuristic_id}:v{heuristic_version}")
        return {"heuristic_id": heuristic_id, "heuristic_version": int(heuristic_version),
                "actions": [a for a in self.evaluate(context, as_of=as_of)
                            if a["rule_id"] == heuristic_id and int(a["rule_version"]) == int(heuristic_version)]}

    def _tariff_vol_condition(self, ctx: dict) -> bool:
        roc = ctx.get("tariff_rate_of_change", 0.0)
        vol_regime = ctx.get("vol_regime", "normal")
        return roc > 5.0 and vol_regime in ("high", "extreme")

    def _shock_condition(self, ctx: dict) -> bool:
        return ctx.get("shock_score", 0.0) > 2.0

    def _divergence_hedge_condition(self, ctx: dict) -> bool:
        divergence_active = ctx.get("divergence_alert_active", False)
        regime_flipped = ctx.get("funding_regime_flipped", False)
        return divergence_active and regime_flipped

    def _negative_carry_condition(self, ctx: dict) -> bool:
        return ctx.get("carry_score", 0.0) < -0.10

    def _stable_rotation_condition(self, ctx: dict) -> bool:
        shock = ctx.get("shock_score", 0.0)
        tariff_roc = ctx.get("tariff_rate_of_change", 0.0)
        return shock > 1.5 or tariff_roc > 8.0

    def _infer_side(self, action_type: str) -> str:
        if action_type in ("reduce_exposure", "reduce_long_perp", "rotate_to_stables"):
            return "sell"
        if action_type == "hedge":
            return "sell"
        return "none"
