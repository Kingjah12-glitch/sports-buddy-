from app.services.market_analyzer_v3 import MARKETS, grade_probability


def analyze_match_v4(home_team, away_team, feats: dict, model, eff_matches=(None, None)) -> dict:
    """Probabilities from the V4 logistic model; the plain Poisson number is
    kept as raw_probability for transparency."""
    raw = {"over_1_5_goals": feats["p15_raw"], "over_2_5_goals": feats["p25_raw"]}
    markets = {}
    for name, _ in MARKETS:
        p = model.predict(name, feats)
        markets[name] = {
            "raw_probability": round(raw[name] * 100, 2),
            "estimated_probability": round(p * 100, 2),
            "fair_odds": round(1.0 / p, 2),
            "probability_tier": grade_probability(p),
            "calibrated": True,
        }
    depth = [d for d in eff_matches if d is not None]
    thin = bool(depth) and min(depth) < 15
    total = feats["lam_h_s"] + feats["lam_a_s"]
    return {
        "status": "analysis_complete",
        "model_version": "v4",
        "data_quality": "LOW" if thin else "OK",
        "data_quality_note": (
            "One team has little recent top-flight history (e.g. newly promoted); "
            "the estimate leans toward the league average." if thin else None),
        "match": {"home_team": home_team, "away_team": away_team},
        "estimated_goals": {"home": round(feats["lam_h_s"], 2),
                            "away": round(feats["lam_a_s"], 2), "total": round(total, 2)},
        "history_depth": {"home_effective_matches": eff_matches[0],
                          "away_effective_matches": eff_matches[1]},
        "markets": markets,
        "disclaimer": (
            "Backtests show bookmaker prices already contain this information. "
            "Only bet when the bookmaker's odds are well above fair_odds, and "
            "treat any single estimate as uncertain."),
    }
