
import math


def poisson_probability_over(expected_goals: float, line: float) -> float:
    """Probability of scoring more goals than the specified line."""
    if expected_goals < 0:
        raise ValueError("Expected goals cannot be negative.")

    max_goals = math.floor(line)

    probability_under_or_equal = sum(
        math.exp(-expected_goals)
        * expected_goals**k
        / math.factorial(k)
        for k in range(max_goals + 1)
    )

    return max(0.0, min(1.0, 1.0 - probability_under_or_equal))


def safe_average(values: list[int], fallback: float) -> float:
    """Return an average, or a fallback if there is no history."""
    return sum(values) / len(values) if values else fallback


def calculate_expected_goals_v2(
    home_scored_at_home: list[int],
    home_conceded_at_home: list[int],
    away_scored_away: list[int],
    away_conceded_away: list[int],
    league_home_avg: float,
    league_away_avg: float,
) -> tuple[float, float]:
    """
    Estimate goals using venue-specific attack and defence strength.

    All inputs must come from matches played before the fixture being tested.
    League averages should also be calculated from earlier matches only.
    """

    if league_home_avg <= 0 or league_away_avg <= 0:
        raise ValueError("League goal averages must be positive.")

    # Use league averages as fallbacks when a team has limited venue history.
    home_attack_avg = safe_average(
        home_scored_at_home, league_home_avg
    )
    home_defence_avg = safe_average(
        home_conceded_at_home, league_away_avg
    )
    away_attack_avg = safe_average(
        away_scored_away, league_away_avg
    )
    away_defence_avg = safe_average(
        away_conceded_away, league_home_avg
    )

    # Ratios above 1 indicate stronger scoring or greater defensive weakness.
    home_attack_strength = home_attack_avg / league_home_avg
    away_defence_weakness = away_defence_avg / league_home_avg

    away_attack_strength = away_attack_avg / league_away_avg
    home_defence_weakness = home_defence_avg / league_away_avg

    home_expected = (
        league_home_avg
        * home_attack_strength
        * away_defence_weakness
    )

    away_expected = (
        league_away_avg
        * away_attack_strength
        * home_defence_weakness
    )

    # Prevent extreme estimates caused by very small samples.
    home_expected = max(0.05, min(home_expected, 5.0))
    away_expected = max(0.05, min(away_expected, 5.0))

    return home_expected, away_expected


def analyze_match_v2(
    home_team: str,
    away_team: str,
    home_scored_at_home: list[int],
    home_conceded_at_home: list[int],
    away_scored_away: list[int],
    away_conceded_away: list[int],
    league_home_avg: float,
    league_away_avg: float,
) -> dict:
    """Analyze over 1.5 and over 2.5 using the V2 goal model."""

    datasets = [
        home_scored_at_home,
        home_conceded_at_home,
        away_scored_away,
        away_conceded_away,
    ]

    if (
        league_home_avg <= 0
        or league_away_avg <= 0
        or any(not values for values in datasets)
    ):
        return {
            "status": "insufficient_data",
            "recommendation": "NO BET",
            "message": "League averages and venue-specific team history are required.",
        }

    if any(
        not isinstance(goal, int)
        or isinstance(goal, bool)
        or goal < 0
        for values in datasets
        for goal in values
    ):
        raise ValueError("Goal counts must be non-negative integers.")

    home_xg, away_xg = calculate_expected_goals_v2(
        home_scored_at_home,
        home_conceded_at_home,
        away_scored_away,
        away_conceded_away,
        league_home_avg,
        league_away_avg,
    )

    total_xg = home_xg + away_xg
    markets = {}

    for line in (1.5, 2.5):
        probability = poisson_probability_over(total_xg, line)
        key = f"over_{str(line).replace('.', '_')}_goals"

        markets[key] = {
            "estimated_probability": round(probability * 100, 2),
        }

    return {
        "status": "analysis_complete",
        "model_version": "v2",
        "match": {
            "home_team": home_team,
            "away_team": away_team,
        },
        "estimated_goals": {
            "home": round(home_xg, 2),
            "away": round(away_xg, 2),
            "total": round(total_xg, 2),
        },
        "markets": markets,
    }
