
import math


def poisson_probability_over(expected_goals: float, line: float) -> float:
    """
    Estimate the probability that total goals exceed a goal line
    using a Poisson model.
    """
    if expected_goals < 0:
        raise ValueError("Expected goals cannot be negative.")

    max_goals = math.floor(line)

    probability_under_or_equal = sum(
        (math.exp(-expected_goals) * expected_goals**k / math.factorial(k))
        for k in range(max_goals + 1)
    )

    return max(0.0, min(1.0, 1.0 - probability_under_or_equal))


def calculate_expected_goals(
    home_scored: list[int],
    home_conceded: list[int],
    away_scored: list[int],
    away_conceded: list[int],
) -> tuple[float, float]:
    """Estimate goals for each team from recent scoring averages."""

    home_expected = (
        sum(home_scored) / len(home_scored)
        + sum(away_conceded) / len(away_conceded)
    ) / 2

    away_expected = (
        sum(away_scored) / len(away_scored)
        + sum(home_conceded) / len(home_conceded)
    ) / 2

    return home_expected, away_expected


def grade_probability(probability: float) -> str:
    """
    Preliminary probability tiers, not guarantees or proof of value.
    """
    if probability >= 0.88:
        return "EXCELLENT"
    elif probability >= 0.80:
        return "GREAT"
    elif probability >= 0.72:
        return "GOOD"
    else:
        return "NO BET"


def analyze_match(
    home_team: str,
    away_team: str,
    home_scored: list[int],
    home_conceded: list[int],
    away_scored: list[int],
    away_conceded: list[int],
) -> dict:
    """Analyze the total-goals markets for a football match."""

    datasets = [
        home_scored,
        home_conceded,
        away_scored,
        away_conceded,
    ]

    if any(len(values) < 5 for values in datasets):
        return {
            "status": "insufficient_data",
            "recommendation": "NO BET",
            "message": "At least five recent matches per team are required.",
        }

    if any(
        not isinstance(goal, int) or isinstance(goal, bool) or goal < 0
        for values in datasets
        for goal in values
    ):
        raise ValueError("Goal counts must be non-negative integers.")

    home_xg, away_xg = calculate_expected_goals(
        home_scored,
        home_conceded,
        away_scored,
        away_conceded,
    )

    total_expected_goals = home_xg + away_xg

    markets = {}

    for line in (1.5, 2.5):
        probability = poisson_probability_over(
            total_expected_goals, line
        )

        markets[f"over_{str(line).replace('.', '_')}_goals"] = {
            "estimated_probability": round(probability * 100, 2),
            "probability_tier": grade_probability(probability),
        }

    return {
        "status": "analysis_complete",
        "match": {
            "home_team": home_team,
            "away_team": away_team,
        },
        "estimated_goals": {
            "home": round(home_xg, 2),
            "away": round(away_xg, 2),
            "total": round(total_expected_goals, 2),
        },
        "markets": markets,
        "disclaimer": (
            "Preliminary statistical estimates, not guaranteed outcomes. "
            "Odds, injuries, team strength, and model calibration are "
            "not yet included. Probability tiers do not establish "
            "betting value."
        ),
    }
