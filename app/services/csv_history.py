"""Legacy helper: last-N goals for a team from the local CSV history.

Now built on history_loader, so it uses the same name matching as the
backtests, reads Latin-1 files, covers the extra-country files, and is cached
instead of re-reading every CSV on every call.
"""
from app.services.history_loader import RAW_DIR as CSV_DIR  # noqa: F401  (kept for compatibility)
from app.services.history_loader import load_all_matches
from app.services.names import normalize_name


def get_team_form(team_name, before_date, league_country=None,
                  league_name=None, limit=5):
    """Goals scored/conceded in the team's most recent matches before a date."""
    key = normalize_name(team_name)
    hints = [normalize_name(h).replace(" ", "") for h in (league_country, league_name) if h]

    pool = [m for m in load_all_matches()
            if m["date"] < before_date and key in (m["hk"], m["ak"])]

    if hints and pool:
        def score(m):
            flat = normalize_name(m["group"].replace("_", " ")).replace(" ", "")
            return sum(1 for h in hints if h in flat)
        best = max(score(m) for m in pool)
        if best > 0:
            pool = [m for m in pool if score(m) == best]

    pool.sort(key=lambda m: m["day"], reverse=True)
    recent = pool[:limit]

    scored, conceded = [], []
    for m in recent:
        if m["hk"] == key:
            scored.append(m["hg"]); conceded.append(m["ag"])
        else:
            scored.append(m["ag"]); conceded.append(m["hg"])

    return {
        "matches_found": len(recent),
        "goals_scored": scored,
        "goals_conceded": conceded,
    }
