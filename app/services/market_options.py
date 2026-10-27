"""Adds the match-result markets (home/draw/away, win-or-draw) to an analysis and
builds the ranked option list with the system's default pick."""

LABELS = {
    "over_1_5_goals": "Over 1.5 goals",
    "over_2_5_goals": "Over 2.5 goals",
    "under_2_5_goals": "Under 2.5 goals",
    "home_or_draw": "Home win or draw",
    "away_or_draw": "Away win or draw",
}


def _entry(p: float) -> dict:
    p = min(0.99, max(0.01, p))
    return {"estimated_probability": round(p * 100, 2), "fair_odds": round(1 / p, 2), "calibrated": True}


def attach_outcome_markets(analysis: dict, probs, source: str) -> dict:
    """probs = (P(home), P(draw), P(away)) as fractions summing to ~1."""
    p_home, p_draw, p_away = probs
    markets = analysis["markets"]
    markets["home_or_draw"] = _entry(p_home + p_draw)
    markets["away_or_draw"] = _entry(p_away + p_draw)
    over25 = markets["over_2_5_goals"]["estimated_probability"] / 100
    markets["under_2_5_goals"] = _entry(1 - over25)

    analysis["outcomes"] = {
        "home": round(p_home * 100, 1), "draw": round(p_draw * 100, 1),
        "away": round(p_away * 100, 1), "source": source,
    }
    options = [{"key": k, "label": LABELS[k],
                "probability": markets[k]["estimated_probability"],
                "fair_odds": markets[k]["fair_odds"]} for k in LABELS]
    options.sort(key=lambda o: -o["probability"])
    analysis["options"] = options
    analysis["pick"] = {
        "basis": "most_likely", **options[0],
        "note": ("Highest probability, not best value: likelier outcomes pay lower odds. "
                 "In backtests the bookmaker's margin made even the safest picks lose money on average."),
    }
    return analysis
