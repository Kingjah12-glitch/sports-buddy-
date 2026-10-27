"""Score a day's saved predictions against the actual results.

    python today.py --refresh-results            (next day: pulls yesterday's results)
    python score_day.py --date 2026-10-24        scores data/today/predictions_2026-10-24.csv

Results come from data/historical/recent_results.csv (filled by --refresh-results).
Every scored match is appended to data/tracking/scorecard.csv so the running totals
show whether the model's probabilities hold up over many matches.
"""
import argparse
import csv
import sys
from datetime import date, timedelta
from pathlib import Path

from app.services.history_loader import RECENT_FILE, parse_date, read_csv_rows
from app.services.names import normalize_name, resolve_key

TRACK_FILE = Path("data/tracking/scorecard.csv")
FIELDS = ["date", "league", "home", "away", "score", "total_goals", "result", "model_version", "xg_total",
          "p_over_1_5", "o15", "p_over_2_5", "o25", "p_1x", "r1x", "p_x2", "rx2",
          "pick", "pick_probability", "pick_hit"]
BASE15, BASE25 = 0.745, 0.50


def _pick_hit(label, g, res):
    return {"Over 1.5 goals": g >= 2, "Over 2.5 goals": g >= 3, "Under 2.5 goals": g <= 2,
            "Home win or draw": res in "HD", "Away win or draw": res in "DA"}.get(label)


def score_rows(pred_rows, result_rows, day):
    """Match predictions to results (same names, kickoff within a day) and flag outcomes."""
    by_key = {}
    for r in result_rows:
        d = parse_date(r.get("Date"))
        if d and abs((d - day).days) <= 1:
            by_key[(normalize_name(r["Home"]), normalize_name(r["Away"]))] = r
    homes = {k[0] for k in by_key}
    aways = {k[1] for k in by_key}
    scored, missing = [], []
    for p in pred_rows:
        hk, ak = normalize_name(p["home"]), normalize_name(p["away"])
        hk, ak = resolve_key(hk, homes) or hk, resolve_key(ak, aways) or ak
        r = by_key.get((hk, ak))
        if r is None:
            missing.append(p)
            continue
        hg, ag = int(r["HG"]), int(r["AG"])
        g, res = hg + ag, ("H" if hg > ag else "D" if hg == ag else "A")
        hit = _pick_hit(p["pick"], g, res)
        scored.append({
            "date": str(day), "league": p["league"], "home": p["home"], "away": p["away"],
            "score": f"{hg}-{ag}", "total_goals": g, "result": res, "model_version": p.get("model_version", ""),
            "xg_total": p["xg_total"],
            "p_over_1_5": p["p_over_1_5"], "o15": int(g >= 2), "p_over_2_5": p["p_over_2_5"], "o25": int(g >= 3),
            "p_1x": p["p_1x"], "r1x": int(res in "HD"), "p_x2": p["p_x2"], "rx2": int(res in "DA"),
            "pick": p["pick"], "pick_probability": p["pick_probability"], "pick_hit": int(bool(hit)),
        })
    return scored, missing


def summarise(rows, title):
    n = len(rows)
    if n == 0:
        return [f"{title}: no matches"]
    f = lambda k: [float(r[k]) for r in rows]
    out = [f"{title}  ({n} matches)",
           f"  goals per match: actual {sum(f('total_goals')) / n:.2f} vs model {sum(f('xg_total')) / n:.2f}"]
    for lab, pk, ok, base in (("Over 1.5", "p_over_1_5", "o15", BASE15), ("Over 2.5", "p_over_2_5", "o25", BASE25),
                              ("Home or draw", "p_1x", "r1x", None), ("Away or draw", "p_x2", "rx2", None)):
        p, y = [v / 100 for v in f(pk)], f(ok)
        brier = sum((a - b) ** 2 for a, b in zip(p, y)) / n
        ref = (f", league-average guess {sum((base - b) ** 2 for b in y) / n:.3f}" if base else "")
        out.append(f"  {lab:13s} happened {int(sum(y)):3d}/{n} ({sum(y) / n:.0%}) | model said {sum(p) / n:.0%} | Brier {brier:.3f}{ref}")
    hits = sum(int(r["pick_hit"]) for r in rows)
    exp = sum(float(r["pick_probability"]) for r in rows) / n
    out.append(f"  system pick (most likely option): hit {hits}/{n} ({hits / n:.0%}), model expected {exp:.0f}%")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", help="prediction date YYYY-MM-DD (default: yesterday)")
    ap.add_argument("--predictions")
    ap.add_argument("--results", default=str(RECENT_FILE))
    ap.add_argument("--no-save", action="store_true", help="do not append to the running scorecard")
    args = ap.parse_args()
    day = date.fromisoformat(args.date) if args.date else date.today() - timedelta(days=1)
    pred_path = Path(args.predictions or f"data/today/predictions_{day}.csv")
    if not pred_path.exists():
        raise SystemExit(f"No predictions file at {pred_path}. Run today.py for that date first.")
    if not Path(args.results).exists():
        raise SystemExit(f"No results file at {args.results}. Run: python today.py --refresh-results")

    scored, missing = score_rows(read_csv_rows(pred_path), read_csv_rows(Path(args.results)), day)
    for line in summarise(scored, f"{day}"):
        print(line)
    if missing:
        print(f"\n{len(missing)} predicted match(es) have no result yet (not finished, or not refreshed):")
        for p in missing:
            print(f"  {p['league']}: {p['home']} v {p['away']}")
    if scored and not args.no_save:
        TRACK_FILE.parent.mkdir(parents=True, exist_ok=True)
        existing = read_csv_rows(TRACK_FILE) if TRACK_FILE.exists() else []
        seen = {(r["date"], r["home"], r["away"]) for r in existing}
        new = [r for r in scored if (r["date"], r["home"], r["away"]) not in seen]
        with open(TRACK_FILE, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(existing + new)
        print(f"\nSaved {len(new)} new rows to {TRACK_FILE}")
        print()
        for line in summarise(existing + new, "RUNNING TOTAL"):
            print(line)
    print("\nFew matches prove nothing: judge the model on hundreds, not on one day.")


if __name__ == "__main__":
    sys.exit(main())
