
import csv
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path

from app.services.history_loader import open_csv
from app.services.market_analyzer import analyze_match
from app.services.market_analyzer_v2 import analyze_match_v2


DATA_DIR = Path("data/historical/raw")
OUTPUT_FILE = Path("data/historical/backtest_v2_results.csv")

MIN_HISTORY = 5
MIN_LEAGUE_MATCHES = 20

MARKETS = {
    "over_1_5_goals": 2,
    "over_2_5_goals": 3,
}


def parse_date(value):
    value = (value or "").strip()

    for fmt in (
        "%d/%m/%Y",
        "%d/%m/%y",
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%Y/%m/%d",
    ):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass

    return None


def load_csv(path):
    matches = []

    with open_csv(path) as f:
        for row in csv.DictReader(f):
            try:
                date = parse_date(row.get("Date"))
                home = (row.get("HomeTeam") or "").strip()
                away = (row.get("AwayTeam") or "").strip()
                hg = int(row["FTHG"])
                ag = int(row["FTAG"])
            except (ValueError, TypeError, KeyError):
                continue

            if not date or not home or not away or hg < 0 or ag < 0:
                continue

            matches.append({
                "date": date,
                "home": home,
                "away": away,
                "hg": hg,
                "ag": ag,
            })

    return sorted(matches, key=lambda m: m["date"])


def evaluate_file(path):
    matches = load_csv(path)

    # V1: recent results regardless of venue.
    all_history = defaultdict(lambda: deque(maxlen=MIN_HISTORY))

    # V2: separate home and away histories.
    home_history = defaultdict(lambda: deque(maxlen=MIN_HISTORY))
    away_history = defaultdict(lambda: deque(maxlen=MIN_HISTORY))

    # League statistics from previously completed dates only.
    previous_home_goals = 0
    previous_away_goals = 0
    previous_match_count = 0

    # Historical over-goals counts for the baseline.
    previous_over_counts = {
        "over_1_5_goals": 0,
        "over_2_5_goals": 0,
    }

    results = []
    dates = sorted({m["date"] for m in matches})

    for match_date in dates:
        today = [m for m in matches if m["date"] == match_date]

        # Evaluate every match before adding results from this date.
        for match in today:
            home = match["home"]
            away = match["away"]

            h_all = list(all_history[home])
            a_all = list(all_history[away])
            h_home = list(home_history[home])
            a_away = list(away_history[away])

            if (
                len(h_all) < MIN_HISTORY
                or len(a_all) < MIN_HISTORY
                or len(h_home) < MIN_HISTORY
                or len(a_away) < MIN_HISTORY
                or previous_match_count < MIN_LEAGUE_MATCHES
            ):
                continue

            league_home_avg = (
                previous_home_goals / previous_match_count
            )
            league_away_avg = (
                previous_away_goals / previous_match_count
            )

            # Model V1.
            v1 = analyze_match(
                home_team=home,
                away_team=away,
                home_scored=[x[0] for x in h_all],
                home_conceded=[x[1] for x in h_all],
                away_scored=[x[0] for x in a_all],
                away_conceded=[x[1] for x in a_all],
            )

            # Model V2.
            v2 = analyze_match_v2(
                home_team=home,
                away_team=away,
                home_scored_at_home=[x[0] for x in h_home],
                home_conceded_at_home=[x[1] for x in h_home],
                away_scored_away=[x[0] for x in a_away],
                away_conceded_away=[x[1] for x in a_away],
                league_home_avg=league_home_avg,
                league_away_avg=league_away_avg,
            )

            if (
                v1.get("status") != "analysis_complete"
                or v2.get("status") != "analysis_complete"
            ):
                continue

            total_goals = match["hg"] + match["ag"]

            for market, threshold in MARKETS.items():
                actual = int(total_goals >= threshold)

                p1 = (
                    v1["markets"][market]["estimated_probability"] / 100
                )
                p2 = (
                    v2["markets"][market]["estimated_probability"] / 100
                )

                # Baseline: frequency of this outcome in earlier matches.
                p_baseline = (
                    previous_over_counts[market]
                    / previous_match_count
                )

                results.append({
                    "date": match_date.isoformat(),
                    "source_file": path.name,
                    "home_team": home,
                    "away_team": away,
                    "home_goals": match["hg"],
                    "away_goals": match["ag"],
                    "market": market,
                    "v1_probability": round(p1, 4),
                    "v2_probability": round(p2, 4),
                    "baseline_probability": round(p_baseline, 4),
                    "actual_outcome": actual,
                    "v1_brier": round((p1 - actual) ** 2, 6),
                    "v2_brier": round((p2 - actual) ** 2, 6),
                    "baseline_brier": round(
                        (p_baseline - actual) ** 2, 6
                    ),
                })

        # Update history only after all predictions for the date.
        for match in today:
            home = match["home"]
            away = match["away"]
            hg = match["hg"]
            ag = match["ag"]

            all_history[home].append((hg, ag))
            all_history[away].append((ag, hg))

            home_history[home].append((hg, ag))
            away_history[away].append((ag, hg))

            previous_home_goals += hg
            previous_away_goals += ag
            previous_match_count += 1

            total_goals = hg + ag

            if total_goals >= 2:
                previous_over_counts["over_1_5_goals"] += 1

            if total_goals >= 3:
                previous_over_counts["over_2_5_goals"] += 1

    return results


def main():
    if not DATA_DIR.exists():
        print(f"CSV directory not found: {DATA_DIR.resolve()}")
        return

    files = sorted(DATA_DIR.glob("*.csv"))

    if not files:
        print(f"No CSV files found in {DATA_DIR.resolve()}")
        return

    all_results = []

    print(f"Found {len(files)} CSV files.")

    for path in files:
        try:
            rows = evaluate_file(path)
            all_results.extend(rows)

            match_count = len(rows) // len(MARKETS)
            print(f"{path.name}: {match_count} matches compared")

        except Exception as exc:
            print(f"Could not process {path.name}: {exc}")

    if not all_results:
        print("\nNo eligible matches were found.")
        print("Check the CSV columns, dates, and historical team data.")
        return

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT_FILE.open(
        "w", encoding="utf-8-sig", newline=""
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=list(all_results[0].keys()),
        )
        writer.writeheader()
        writer.writerows(all_results)

    print("\n========== V1 vs V2 vs BASELINE ==========")

    for market in MARKETS:
        rows = [r for r in all_results if r["market"] == market]
        count = len(rows)

        if not count:
            continue

        actual_rate = (
            sum(r["actual_outcome"] for r in rows) / count * 100
        )

        v1_avg = (
            sum(r["v1_probability"] for r in rows) / count * 100
        )
        v2_avg = (
            sum(r["v2_probability"] for r in rows) / count * 100
        )
        baseline_avg = (
            sum(r["baseline_probability"] for r in rows)
            / count * 100
        )

        v1_brier = sum(r["v1_brier"] for r in rows) / count
        v2_brier = sum(r["v2_brier"] for r in rows) / count
        baseline_brier = (
            sum(r["baseline_brier"] for r in rows) / count
        )

        print(f"\n{market}")
        print(f"Matches compared: {count}")
        print(f"Actual frequency: {actual_rate:.2f}%")
        print(f"V1 average probability: {v1_avg:.2f}%")
        print(f"V2 average probability: {v2_avg:.2f}%")
        print(f"Baseline average probability: {baseline_avg:.2f}%")
        print(f"V1 Brier score: {v1_brier:.4f}")
        print(f"V2 Brier score: {v2_brier:.4f}")
        print(f"Baseline Brier score: {baseline_brier:.4f}")

        scores = {
            "V1": v1_brier,
            "V2": v2_brier,
            "Baseline": baseline_brier,
        }

        best_model = min(scores, key=scores.get)
        print(f"Best score on this dataset: {best_model}")

    print(f"\nDetailed results saved to: {OUTPUT_FILE.resolve()}")
    print("Lower Brier scores are better.")
    print("These scores measure probability accuracy, not profit.")


if __name__ == "__main__":
    main()
