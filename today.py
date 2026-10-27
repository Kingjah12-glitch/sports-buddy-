"""Run the V3 model on a day's matches.

    python today.py                          fixtures for today from API-Football
    python today.py --date 2026-10-18        a specific day
    python today.py --refresh-results        first pull yesterday's finished results into
                                             recent_results.csv (run it daily; free API plans
                                             only serve yesterday..tomorrow)
    python today.py --fixtures-file f.csv    offline: columns Date,Time,Country,League,Home,Away
                                             (+ optional PH,PD,PA win % for cross-league games such as
                                             the Champions League)
    python today.py --odds odds.csv          add your bookmaker odds to see the edge
                                             (columns Home,Away,over_1_5,over_2_5)

Output is printed and saved to data/today/predictions_<date>.csv
"""
import argparse
import asyncio
import csv
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from app.services.daily import (fixtures_from_api_items, fixtures_from_file, get_tz,  # noqa: F401
                                merge_recent_results, predict_rows, predictable,
                                results_from_api_items, write_predictions_csv)
from app.services.history_loader import RECENT_FILE, read_csv_rows
from app.services.names import normalize_name, resolve_key
from app.services.ratings_store import get_state

OUT_DIR = Path("data/today")


# ------------------------------------------------------------------ providers
def load_odds(path):
    odds = {}
    for r in read_csv_rows(Path(path)):
        r = {k.strip().lower(): v for k, v in r.items()}
        key = (normalize_name(r.get("home")), normalize_name(r.get("away")))
        odds[key] = {c: (float(r[c]) if r.get(c) else None) for c in ("over_1_5", "over_2_5")}
    return odds


def print_table(rows, odds=False):
    head = (f"{'KO':5} {'League':14} {'Match':40} {'xG':>9} {'O1.5':>6} {'O2.5':>6} {'1X':>6} {'X2':>6}  "
            f"{'system pick (most likely)':30} data")
    if odds:
        head += "   edge1.5 edge2.5"
    print(head)
    print("-" * len(head))
    for r in rows:
        match = f"{r['home']} v {r['away']}"[:40]
        pick = f"{r['pick']} {r['pick_probability']:.0f}%"
        line = (f"{r['kickoff']:5} {str(r['league'])[:14]:14} {match:40} "
                f"{r['xg_home']:.1f}-{r['xg_away']:.1f} {r['p_over_1_5']:5.1f}% {r['p_over_2_5']:5.1f}% "
                f"{r['p_1x']:5.1f}% {r['p_x2']:5.1f}%  {pick:30} {r['data_quality']}")
        if odds:
            f = lambda v: "  -   " if v is None else f"{v:+5.1f}pp"
            line += f"   {f(r.get('edge_o15_pp'))} {f(r.get('edge_o25_pp'))}"
        print(line)


# ------------------------------------------------------------------ main
async def _fetch_day(day: date):
    from app.services.sports_api import fetch_football_data
    data = await fetch_football_data("fixtures", {"date": day.isoformat()})
    return data.get("response", [])


async def main_async(args):
    try:
        tz = get_tz(args.tz)
    except ValueError as exc:
        raise SystemExit(str(exc))
    day = date.fromisoformat(args.date) if args.date else datetime.now(tz).date()
    state = get_state()

    if args.refresh_results:
        from app.services.sports_api import SportsAPIError
        new = []
        for back in range(1, args.refresh_days + 1):
            target = day - timedelta(days=back)
            try:
                new += results_from_api_items(await _fetch_day(target), state)
            except SportsAPIError as exc:
                # e.g. free plans only serve yesterday..tomorrow
                print(f"  Skipped results for {target}: {exc}")
        added = merge_recent_results(new)
        print(f"Results refresh: {added} new finished matches added to {RECENT_FILE}")
        get_state.cache_clear()
        state = get_state()

    if args.fixtures_file:
        fixtures = fixtures_from_file(args.fixtures_file, tz)
        fixtures = [f for f in fixtures if f["kickoff"].date() == day] or fixtures
    else:
        from app.services.sports_api import SportsAPIError
        try:
            fixtures = fixtures_from_api_items(await _fetch_day(day), tz)
        except SportsAPIError as exc:
            raise SystemExit(f"Could not fetch fixtures for {day}: {exc}")

    covered = predictable(fixtures, state)
    odds = load_odds(args.odds) if args.odds else None
    rows, unmatched = predict_rows(covered, state, odds)

    print(f"\n{day}  |  {len(fixtures)} fixtures from provider, {len(covered)} in covered "
          f"competitions, {len(rows)} predicted  |  history through {state.last_date}  |  times {args.tz}\n")
    print_table(rows, bool(odds))
    if unmatched:
        print("\nCould not match team names (add them to data/team_aliases.json):")
        for fx in unmatched:
            print(f"  {fx['league']}: {fx['home']} v {fx['away']}")

    out = OUT_DIR / f"predictions_{day}.csv"
    if write_predictions_csv(rows, out):
        print(f"\nSaved {out}")
    print("\nReminder: backtests show bookmaker prices are at least as accurate as this model. "
          "Probabilities are calibrated; an 'edge' only matters if it survives your own checking.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date")
    ap.add_argument("--tz", default="Africa/Lagos")
    ap.add_argument("--refresh-results", action="store_true")
    ap.add_argument("--refresh-days", type=int, default=1,
                    help="how many past days to fetch results for (free API plans allow only 1)")
    ap.add_argument("--fixtures-file")
    ap.add_argument("--odds")
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
