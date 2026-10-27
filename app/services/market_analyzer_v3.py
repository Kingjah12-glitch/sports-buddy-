from app.services.calibration import apply_calibrator
from app.services.ratings import poisson_over_probabilities

MARKETS = (("over_1_5_goals", 0), ("over_2_5_goals", 1))


def grade_probability(p: float) -> str:
    """Likelihood tier on the CALIBRATED probability. A high tier is NOT a
    value signal: compare fair_odds with the bookmaker's price first."""
    if p >= 0.88:
        return "EXCELLENT"
    if p >= 0.80:
        return "GREAT"
    if p >= 0.72:
        return "GOOD"
    return "NO BET"


def analyze_match_v3(home_team, away_team, lam_home, lam_away,
                     calibrators=None, eff_matches=(None, None)) -> dict:
    calibrators = calibrators or {}
    raw = poisson_over_probabilities(lam_home + lam_away)
    markets = {}
    for name, idx in MARKETS:
        cal = apply_calibrator(calibrators.get(name), raw[idx])
        markets[name] = {
            "raw_probability": round(raw[idx] * 100, 2),
            "estimated_probability": round(cal * 100, 2),
            "fair_odds": round(1.0 / cal, 2),
            "probability_tier": grade_probability(cal),
            "calibrated": name in calibrators,
        }
    depth = [d for d in eff_matches if d is not None]
    thin = bool(depth) and min(depth) < 15
    return {
        "status": "analysis_complete",
        "data_quality": "LOW" if thin else "OK",
        "data_quality_note": (
            "One team has little recent top-flight history (e.g. newly promoted); "
            "the estimate leans toward the league average." if thin else None),
        "model_version": "v3",
        "match": {"home_team": home_team, "away_team": away_team},
        "estimated_goals": {
            "home": round(lam_home, 2),
            "away": round(lam_away, 2),
            "total": round(lam_home + lam_away, 2),
        },
        "history_depth": {"home_effective_matches": eff_matches[0],
                          "away_effective_matches": eff_matches[1]},
        "markets": markets,
        "disclaimer": (
            "Backtests show bookmaker prices already contain this information. "
            "Only bet when the bookmaker's odds are well above fair_odds, and "
            "treat any single estimate as uncertain."
        ),
    }
