
import csv
import math
import re
import unicodedata
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path

from app.services.history_loader import open_csv
from app.services.market_analyzer import analyze_match
from app.services.names import normalize_name as normalize_team


# Project folders
DATA_DIR = Path("data/historical/raw")
OUTPUT_FILE = Path("data/historical/backtest_results.csv")

MIN_HISTORY = 5
MARKETS = {
    "over_1_5_goals": 2,
    "over_2_5_goals": 3,
}



def parse_date(value):
    value = value.strip()

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
            continue

    return None


def load_matches(path):
    matches = []

    with open_csv(path) as f:
        reader = csv.DictReader(f)

        for row in reader:
            try:
                date = parse_date(row.get("Date", ""))
                home = row.get("HomeTeam", "").strip()
                away = row.get("AwayTeam", "").strip()
                home_goals = int(row["FTHG"])
                away_goals = int(row["FTAG"])
            except (ValueError, TypeError, KeyError):
                continue

            if (
                date is None
                or not home
                or not away
                or home_goals < 0
                or away_goals < 0
            ):
                continue

            matches.append({
                "date": date,
                "home": home,
                "away": away,
                "hg": home_goals,
                "ag": away_goals,
            })

    return sorted(matches, key=lambda m: m["date"])


def backtest_file(path):
    matches = load_matches(path)

    # Store each team's recent matches:
    # (goals scored, goals conceded)
    history = defaultdict(lambda: deque(maxlen=MIN_HISTORY))
    results = []

    # Process all matches on a date BEFORE adding that date's results.
    dates = sorted({match["date"] for match in matches})

    for match_date in dates:
        todays_matches = [
            m for m in matches if m["date"] == match_date
        ]

        # Make predictions using only earlier dates.
        for match in todays_matches:
            home_key = normalize_team(match["home"])
            away_key = normalize_team(match["away"])

            home_history = list(history[home_key])
            away_history = list(history[away_key])

            if (
                not home_key
                or not away_key
                or len(home_history) < MIN_HISTORY
                or len(away_history) < MIN_HISTORY
            ):
                continue

            prediction = analyze_match(
                home_team=match["home"],
                away_team=match["away"],
                home_scored=[x[0] for x in home_history],
                home_conceded=[x[1] for x in home_history],
                away_scored=[x[0] for x in away_history],
                away_conceded=[x[1] for x in away_history],
            )

            if prediction.get("status") != "analysis_complete":
                continue

            total_goals = match["hg"] + match["ag"]

            for market, threshold in MARKETS.items():
                probability = (
                    prediction["markets"][market]["estimated_probability"]
                    / 100.0
                )
                actual = int(total_goals >= threshold)

                results.append({
                    "date": match_date.isoformat(),
                    "source_file": path.name,
                    "home_team": match["home"],
                    "away_team": match["away"],
                    "home_goals": match["hg"],
                    "away_goals": match["ag"],
                    "market": market,
                    "predicted_probability": round(probability, 4),
                    "actual_outcome": actual,
                    "brier_component": round(
                        (probability - actual) ** 2, 6
                    ),
                    "predicted_correct_at_50pct": int(
                        (probability >= 0.5) == bool(actual)
                    ),
                })

        # Only after all predictions for this date, add its results.
        for match in todays_matches:
            home_key = normalize_team(match["home"])
            away_key = normalize_team(match["away"])

            history[home_key].append(
                (match["hg"], match["ag"])
            )
            history[away_key].append(
                (match["ag"], match["hg"])
            )

    return results


def main():
    if not DATA_DIR.exists():
        print(f"ERROR: CSV folder not found: {DATA_DIR.resolve()}")
        print("Run this script from your sports buddy project root.")
        return

    csv_files = sorted(DATA_DIR.glob("*.csv"))

    if not csv_files:
        print(f"No CSV files found in {DATA_DIR.resolve()}")
        return

    all_results = []
    print(f"Found {len(csv_files)} CSV files.")

    for path in csv_files:
        try:
            results = backtest_file(path)
            all_results.extend(results)
            print(f"{path.name}: tested {len(results) // 2} matches")
        except Exception as exc:
            print(f"Skipped {path.name}: {exc}")

    if not all_results:
        print("\nNo eligible matches found.")
        print("Check the CSV columns, date formats, and team history.")
        return

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT_FILE.open(
        "w", encoding="utf-8-sig", newline=""
    ) as f:
        writer = csv.DictWriter(
            f, fieldnames=list(all_results[0].keys())
        )
        writer.writeheader()
        writer.writerows(all_results)

    print("\n========== BACKTEST SUMMARY ==========")

    for market in MARKETS:
        rows = [
            r for r in all_results if r["market"] == market
        ]

        if not rows:
            continue

        count = len(rows)
        brier = sum(
            r["brier_component"] for r in rows
        ) / count
        accuracy = sum(
            r["predicted_correct_at_50pct"] for r in rows
        ) / count * 100
        avg_probability = sum(
            r["predicted_probability"] for r in rows
        ) / count * 100
        actual_rate = sum(
            r["actual_outcome"] for r in rows
        ) / count * 100

        print(f"\n{market}")
        print(f"Matches tested: {count}")
        print(f"Average predicted probability: {avg_probability:.2f}%")
        print(f"Actual over-goals frequency: {actual_rate:.2f}%")
        print(f"Brier score: {brier:.4f} (lower is better)")
        print(f"50% threshold accuracy: {accuracy:.2f}%")

    print(f"\nDetailed results saved to: {OUTPUT_FILE.resolve()}")
    print("These results are historical tests, not a guarantee of future performance.")


if __name__ == "__main__":
    main()
