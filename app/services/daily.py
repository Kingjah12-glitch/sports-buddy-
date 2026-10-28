"""Shared logic for 'predict a day's matches' (used by today.py and the web API)."""
import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from app.services.cross_league import devig_percentages
from app.services.history_loader import RECENT_FILE, read_csv_rows
from app.services.names import normalize_name, resolve_key

# League display order in the UI (country, league). Anything else follows alphabetically.
LEAGUE_ORDER = ["world|champions league", "world|uefa champions league", "england|premier league", "spain|la liga", "italy|serie a",
                "germany|bundesliga", "france|ligue 1", "usa|mls"]


def get_tz(name):
    """ZoneInfo needs the 'tzdata' package on Windows; fall back to fixed offsets
    for zones without daylight saving so we never crash on that."""
    try:
        return ZoneInfo(name)
    except Exception:
        fixed = {"Africa/Lagos": 1, "UTC": 0, "Africa/Accra": 0, "Africa/Nairobi": 3,
                 "Africa/Johannesburg": 2}
        if name in fixed:
            return timezone(timedelta(hours=fixed[name]), name)
        raise ValueError(f"Time zone '{name}' not found. Run: pip install tzdata")


UPCOMING = {"NS", "TBD"}
LIVE = {"1H", "HT", "2H", "ET", "BT", "P", "LIVE", "INT", "SUSP"}
FINISHED = {"FT", "AET", "PEN"}


def status_kind(short):
    """'upcoming' | 'live' | 'finished' (None for postponed / cancelled / abandoned)."""
    if short in UPCOMING:
        return "upcoming"
    if short in LIVE:
        return "live"
    if short in FINISHED:
        return "finished"
    return None


def fixtures_from_api_items(items, tz):
    """API-Football 'fixtures?date=' items -> simple dicts.

    Matches that have already started or finished are KEPT (with status and score), so the
    page still shows the whole day after kickoff. Postponed / cancelled games are dropped.
    Predictions only use results up to yesterday, so they stay valid pre-match numbers."""
    out = []
    for it in items:
        short = it.get("fixture", {}).get("status", {}).get("short")
        kind = status_kind(short)
        if kind is None:
            continue
        try:
            kick = datetime.fromisoformat(it["fixture"]["date"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        goals = it.get("goals") or {}
        out.append({
            "kickoff": kick.astimezone(tz),
            "fixture_id": it["fixture"].get("id"),
            "country": it.get("league", {}).get("country"),
            "league": it.get("league", {}).get("name"),
            "home": it["teams"]["home"]["name"],
            "away": it["teams"]["away"]["name"],
            "status": kind, "status_short": short,
            "goals": (goals.get("home"), goals.get("away")),
        })
    return out


def fixtures_from_file(path, tz):
    """CSV with columns Date,Time(UTC),Country,League,Home,Away."""
    out = []
    for r in read_csv_rows(Path(path)):
        kick = datetime.fromisoformat(f"{r['Date']}T{r['Time']}:00").replace(tzinfo=timezone.utc)
        probs = None
        try:
            probs = devig_percentages(float(r["PH"]), float(r["PD"]), float(r["PA"]))
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            pass
        out.append({"kickoff": kick.astimezone(tz), "fixture_id": None, "country": r["Country"],
                    "league": r["League"], "home": r["Home"], "away": r["Away"], "probs": probs})
    return out


def predictable(fixtures, state):
    """Fixtures we can estimate: domestic competitions in the history, or any match
    that comes with outside win probabilities (cross-league mode)."""
    return [f for f in fixtures if state.covered_groups(f["country"], f["league"]) or f.get("probs")]


def predict_rows(fixtures, state, odds=None):
    rows, unmatched = [], []
    for fx in fixtures:
        pred = None
        if state.covered_groups(fx["country"], fx["league"]):
            pred = state.predict_fixture(fx["home"], fx["away"], fx["kickoff"].date(),
                                         fx["country"], fx["league"])
        if pred is not None:
            a = state.analyze(fx["home"], fx["away"], pred)
        elif fx.get("probs"):
            cross = state.predict_cross_league(fx["home"], fx["away"], fx["kickoff"].date(),
                                               fx["probs"][0], fx["probs"][2])
            if cross is None:
                unmatched.append(fx)
                continue
            a = state.analyze_cross(fx["home"], fx["away"], cross, fx["probs"])
        else:
            unmatched.append(fx)
            continue
        m15, m25 = a["markets"]["over_1_5_goals"], a["markets"]["over_2_5_goals"]
        row = {
            "kickoff": fx["kickoff"].strftime("%H:%M"), "kickoff_iso": fx["kickoff"].isoformat(),
            "country": fx.get("country"), "league": fx["league"],
            "home": fx["home"], "away": fx["away"], "fixture_id": fx.get("fixture_id"),
            "xg_home": a["estimated_goals"]["home"], "xg_away": a["estimated_goals"]["away"],
            "xg_total": a["estimated_goals"]["total"],
            "p_over_1_5": m15["estimated_probability"], "fair_odds_o15": m15["fair_odds"],
            "p_over_2_5": m25["estimated_probability"], "fair_odds_o25": m25["fair_odds"],
            "data_quality": a["data_quality"], "data_quality_note": a.get("data_quality_note"),
            "model_version": a["model_version"],
            "status": fx.get("status") or "upcoming", "status_short": fx.get("status_short"),
            "home_goals": (fx.get("goals") or (None, None))[0], "away_goals": (fx.get("goals") or (None, None))[1],
            "p_home": a["outcomes"]["home"], "p_draw": a["outcomes"]["draw"], "p_away": a["outcomes"]["away"],
            "p_1x": a["markets"]["home_or_draw"]["estimated_probability"],
            "fair_odds_1x": a["markets"]["home_or_draw"]["fair_odds"],
            "p_x2": a["markets"]["away_or_draw"]["estimated_probability"],
            "fair_odds_x2": a["markets"]["away_or_draw"]["fair_odds"],
            "pick": a["pick"]["label"], "pick_probability": a["pick"]["probability"],
            "outcomes": a["outcomes"], "options": a["options"], "pick_detail": a["pick"],
        }
        if odds:
            key = (normalize_name(fx["home"]), normalize_name(fx["away"]))
            for label, col, p in (("o15", "over_1_5", m15), ("o25", "over_2_5", m25)):
                price = odds.get(key, {}).get(col)
                row[f"book_{label}"] = price
                row[f"edge_{label}_pp"] = (None if not price else
                                           round(p["estimated_probability"] - 100 / price, 1))
        rows.append(row)
    rows.sort(key=lambda r: (r["kickoff"], r["league"]))
    return rows, unmatched


def group_by_league(rows):
    """Rows -> list of {country, league, matches[]} in display order."""
    groups = {}
    for r in rows:
        groups.setdefault((r.get("country") or "", r["league"]), []).append(r)

    def order(item):
        country, league = item[0]
        key = f"{normalize_name(country)}|{league.lower()}"
        key2 = f"{country.lower()}|{league.lower()}"
        for k in (key2, key):
            if k in LEAGUE_ORDER:
                return (LEAGUE_ORDER.index(k), "")
        return (len(LEAGUE_ORDER), f"{country} {league}".lower())

    out = []
    for (country, league), matches in sorted(groups.items(), key=order):
        out.append({"key": f"{country}|{league}", "country": country, "league": league,
                    "matches": sorted(matches, key=lambda m: m["kickoff"])})
    return out


DONE = {"FT", "AET", "PEN"}


def results_from_api_items(items, state):
    """Finished API-Football items -> rows for recent_results.csv."""
    rows = []
    for it in items:
        if it.get("fixture", {}).get("status", {}).get("short") not in DONE:
            continue
        goals = it.get("goals", {})
        if goals.get("home") is None or goals.get("away") is None:
            continue
        home, away = it["teams"]["home"]["name"], it["teams"]["away"]["name"]
        groups = state.covered_groups(it["league"].get("country"), it["league"].get("name"))
        group = None
        for g in groups:
            known = state.teams_by_group[g]
            if resolve_key(normalize_name(home), known) and resolve_key(normalize_name(away), known):
                group = g
                break
        if group is None and len(groups) == 1:
            group = groups[0]               # e.g. a newly promoted club
        if group is None:
            continue
        rows.append({"Date": it["fixture"]["date"][:10], "Competition": group,
                     "Home": home, "Away": away, "HG": goals["home"], "AG": goals["away"]})
    return rows


def merge_recent_results(new_rows, path=RECENT_FILE):
    existing = read_csv_rows(path) if Path(path).exists() else []
    seen = {(r["Date"], r["Competition"], normalize_name(r["Home"]), normalize_name(r["Away"]))
            for r in existing}
    added = 0
    for r in new_rows:
        key = (r["Date"], r["Competition"], normalize_name(r["Home"]), normalize_name(r["Away"]))
        if key not in seen:
            seen.add(key)
            existing.append(r)
            added += 1
    existing.sort(key=lambda r: r["Date"])
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["Date", "Competition", "Home", "Away", "HG", "AG"])
        w.writeheader()
        w.writerows(existing)
    return added


# ------------------------------------------------------------------ prediction


def write_predictions_csv(rows, path):
    """Flat CSV of a day's predictions (nested option lists are left out)."""
    if not rows:
        return False
    flat = [k for k, v in rows[0].items() if not isinstance(v, (list, dict))]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=flat, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return True


async def refresh_results(day, state, fetch, days=1):
    """Pull finished matches of the previous `days` days into recent_results.csv.
    `fetch` is the API-Football fixtures fetcher. Returns how many new matches were added."""
    from app.services.sports_api import SportsAPIError
    new = []
    for back in range(1, days + 1):
        target = day - timedelta(days=back)
        try:
            data = await fetch("fixtures", {"date": target.isoformat()})
            new += results_from_api_items(data.get("response", []), state)
        except SportsAPIError as exc:
            print(f"  Skipped results for {target}: {exc}")
    return merge_recent_results(new)
