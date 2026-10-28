"""One place that turns 'a day' into the JSON the website shows.

Used by the live API (/api/v1/predictions/day) and by build_site.py, which writes
the same JSON to static files so the site works with no server (GitHub Pages)."""
from collections import Counter
from datetime import datetime, timezone

from fastapi.concurrency import run_in_threadpool

from app.services.daily import (fixtures_from_api_items, fixtures_from_file, group_by_league,
                                predict_rows, predictable)
from app.services.sports_api import SportsAPIError


class DayUnavailable(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


def match_json(r: dict) -> dict:
    return {
        "kickoff": r["kickoff"], "kickoff_iso": r.get("kickoff_iso"), "fixture_id": r.get("fixture_id"),
        "home": r["home"], "away": r["away"],
        "xg": {"home": r["xg_home"], "away": r["xg_away"], "total": r["xg_total"]},
        "over_1_5": {"probability": r["p_over_1_5"], "fair_odds": r["fair_odds_o15"]},
        "over_2_5": {"probability": r["p_over_2_5"], "fair_odds": r["fair_odds_o25"]},
        "data_quality": r["data_quality"], "data_quality_note": r.get("data_quality_note"),
        "outcomes": r["outcomes"], "options": r["options"], "pick": r["pick_detail"],
        "status": r.get("status", "upcoming"), "status_short": r.get("status_short"),
        "score": ({"home": r["home_goals"], "away": r["away_goals"]}
                  if r.get("home_goals") is not None and r.get("away_goals") is not None else None),
    }


async def build_day_payload(day, zone, tz_name, source, state, fetch, today_dir):
    """Returns (payload, flat_rows). Raises DayUnavailable with an HTTP-style status."""
    file_path = today_dir / f"fixtures_{day.isoformat()}.csv"
    fixtures, used, fallback_reason = [], None, None

    if source in ("auto", "api"):
        try:
            data = await fetch("fixtures", {"date": day.isoformat()})
            fixtures, used = fixtures_from_api_items(data.get("response", []), zone), "api-football"
            if file_path.exists():      # add cross-league games (e.g. Champions League) from your file
                known = {(f["home"], f["away"]) for f in fixtures}
                extra = [f for f in fixtures_from_file(file_path, zone)
                         if f.get("probs") and f["kickoff"].date() == day and (f["home"], f["away"]) not in known]
                if extra:
                    fixtures, used = fixtures + extra, "api-football+file"
        except SportsAPIError as error:
            if source == "api":
                raise DayUnavailable(502, str(error)) from error
            fallback_reason = str(error)

    if used is None:
        if not file_path.exists():
            raise DayUnavailable(404, (
                f"No fixtures available for {day}. " +
                (f"Live provider said: {fallback_reason}. " if fallback_reason else "") +
                f"You can also provide {file_path.name} in data/today/."))
        fixtures, used = fixtures_from_file(file_path, zone), f"file:{file_path.name}"
        fixtures = [f for f in fixtures if f["kickoff"].date() == day] or fixtures

    covered = predictable(fixtures, state)
    not_covered = Counter(f"{f['country']} - {f['league']}" for f in fixtures if f not in covered)
    rows, unmatched = await run_in_threadpool(predict_rows, covered, state)

    leagues = [{"key": g["key"], "country": g["country"], "league": g["league"],
                "matches": [match_json(m) for m in g["matches"]]}
               for g in group_by_league(rows)]
    payload = {
        "date": day.isoformat(), "timezone": tz_name, "source": used,
        "fallback_reason": fallback_reason,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "model_version": rows[0]["model_version"] if rows else None,
        "data_through": str(state.last_date),
        "summary": {"fixtures_from_provider": len(fixtures), "predicted": len(rows),
                    "leagues": len(leagues), "team_names_not_matched": len(unmatched)},
        "leagues": leagues,
        "unmatched": [{"league": f["league"], "home": f["home"], "away": f["away"]} for f in unmatched],
        "not_covered": [{"competition": k, "matches": v} for k, v in sorted(not_covered.items())][:60],
        "notice": ("Backtests show bookmaker prices are at least as accurate as these estimates. "
                   "Use fair odds as a reference only."),
    }
    return payload, rows
