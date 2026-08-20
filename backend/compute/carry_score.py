from backend.core.derivatives_observations import annualize_rate


def compute_carry_score(funding_rate: float, interval_seconds: int) -> float:
    return annualize_rate(funding_rate, interval_seconds)
