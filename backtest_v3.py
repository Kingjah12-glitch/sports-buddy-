"""Backtest V3 - honest, walk-forward, with a held-out test period.

Run from the project root:   python backtest_v3.py

What it does
  1. Loads every CSV (European + extra-country files, UTF-8 or Latin-1).
  2. Walks forward day by day: predict a day's matches using only earlier
     matches, THEN add that day's results.
  3. Tunes the rating parameters on the TRAIN period only.
  4. Fits probability calibration on the TRAIN period only.
  5. Reports everything on the untouched TEST period:
       - Brier / log-loss / AUC vs a constant baseline
       - calibration by tier
       - comparison with the bookmakers' own (de-vigged) Over 2.5 price
       - ROI of betting the model's "edge" against real odds, with 95% CI
  6. Saves calibration + parameters for the live app (data/models/).
"""
import json
import math
import sys
from datetime import date
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

from app.services.calibration import apply_calibrator, fit_calibrator
from app.services.history_loader import load_all_matches
from app.services.ratings import RatingEngine, poisson_over_probabilities

TRAIN_END = date(2022, 6, 30)          # everything after this is the test set
MODEL_DIR = Path("data/models")
RESULTS_FILE = Path("data/historical/backtest_v3_results.csv")
REPORT_FILE = Path("data/historical/backtest_v3_report.md")

PARAM_GRID = {
    "k": [4.0, 8.0, 16.0],
    "tau_days": [180.0, 365.0, 730.0],
    "adjust": [False, True],
}
MIN_EFF = 6.0
BASE_PRIOR_WEIGHT = 20.0               # for the rolling "league over-rate" baseline
EDGE_THRESHOLDS = [0.0, 0.03, 0.05, 0.10]


# ------------------------------------------------------------------ walk-forward
def walk_forward(matches, k, tau_days, adjust):
    """Predict each day using only earlier days. Returns a list of row dicts."""
    engine = RatingEngine(k=k, tau_days=tau_days, adjust=adjust, min_eff=MIN_EFF)
    base = {}                          # group -> [n, over15, over25]
    rows = []
    i, total = 0, len(matches)

    while i < total:
        j = i
        day = matches[i]["day"]
        while j < total and matches[j]["day"] == day:
            j += 1
        batch = matches[i:j]

        for m in batch:                # 1) predict with pre-day information
            pred = engine.predict(m["group"], m["hk"], m["ak"], day)
            if pred is None:
                continue
            lam_h, lam_a, w_h, w_a = pred
            p15, p25 = poisson_over_probabilities(lam_h + lam_a)
            n, c15, c25 = base.get(m["group"], (0, 0, 0))
            goals = m["hg"] + m["ag"]
            rows.append({
                "date": m["date"], "group": m["group"],
                "home_team": m["home"], "away_team": m["away"],
                "home_goals": m["hg"], "away_goals": m["ag"],
                "lam_home": lam_h, "lam_away": lam_a,
                "eff_home": w_h, "eff_away": w_a,
                "p15_raw": p15, "p25_raw": p25,
                "base15": (c15 + 0.745 * BASE_PRIOR_WEIGHT) / (n + BASE_PRIOR_WEIGHT),
                "base25": (c25 + 0.50 * BASE_PRIOR_WEIGHT) / (n + BASE_PRIOR_WEIGHT),
                "y15": int(goals >= 2), "y25": int(goals >= 3),
                "o_avg": m["o_avg"], "u_avg": m["u_avg"],
                "o_max": m["o_max"], "u_max": m["u_max"],
            })

        for m in batch:                # 2) only now reveal the results
            engine.update(m["group"], m["hk"], m["ak"], day, m["hg"], m["ag"])
            n, c15, c25 = base.get(m["group"], (0, 0, 0))
            goals = m["hg"] + m["ag"]
            base[m["group"]] = (n + 1, c15 + (goals >= 2), c25 + (goals >= 3))
        i = j
    return rows


# ------------------------------------------------------------------ metrics
def brier(p, y):
    p, y = np.asarray(p, float), np.asarray(y, float)
    return float(np.mean((p - y) ** 2))


def logloss(p, y):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    y = np.asarray(y, float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def logit(p):
    p = np.clip(np.asarray(p, float), 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def score_params(train_matches, k, tau, adjust):
    """Calibrate on the first 70% of train rows, score Brier on the last 30%."""
    rows = walk_forward(train_matches, k, tau, adjust)
    cut = int(len(rows) * 0.7)
    fit_part, eval_part = rows[:cut], rows[cut:]
    total = 0.0
    for market in ("15", "25"):
        cal = fit_calibrator([r[f"p{market}_raw"] for r in fit_part],
                             [r[f"y{market}"] for r in fit_part])
        preds = [apply_calibrator(cal, r[f"p{market}_raw"]) for r in eval_part]
        total += brier(preds, [r[f"y{market}"] for r in eval_part])
    return total / 2.0, len(rows)


# ------------------------------------------------------------------ main
def main():
    try:
        matches = load_all_matches()
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}\nRun this script from your sports buddy project root.")
        return 1

    print(f"Loaded {len(matches):,} matches from "
          f"{len({m['group'] for m in matches})} competitions "
          f"({matches[0]['date']} -> {matches[-1]['date']}).")

    train_matches = [m for m in matches if m["date"] <= TRAIN_END]
    print(f"Train matches (<= {TRAIN_END}): {len(train_matches):,}")

    # ---- 1. tune on the train period only
    print("\nTuning rating parameters on the TRAIN period only...")
    best = None
    for k, tau, adjust in product(PARAM_GRID["k"], PARAM_GRID["tau_days"],
                                  PARAM_GRID["adjust"]):
        score, n_rows = score_params(train_matches, k, tau, adjust)
        print(f"  k={k:<5} tau={tau:<6} adjust={str(adjust):<5} "
              f"held-out-train Brier={score:.5f} (rows={n_rows:,})")
        if best is None or score < best[0]:
            best = (score, k, tau, adjust)
    _, k, tau, adjust = best
    print(f"\nChosen parameters: k={k}, tau_days={tau}, adjust={adjust}")

    # ---- 2. final walk-forward over all data
    rows = walk_forward(matches, k, tau, adjust)
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    train = df[df["date"].dt.date <= TRAIN_END].copy()
    test = df[df["date"].dt.date > TRAIN_END].copy()
    print(f"Predictions: train={len(train):,}  test={len(test):,}")
    if len(test) < 1000:
        print("Not enough test data to report.")
        return 1

    # ---- 3. calibration fitted on TRAIN only (used for the honest report)
    cals = {}
    for market in ("15", "25"):
        cals[market] = fit_calibrator(train[f"p{market}_raw"], train[f"y{market}"])
        for frame in (train, test):
            frame[f"p{market}_cal"] = [
                apply_calibrator(cals[market], p) for p in frame[f"p{market}_raw"]
            ]
    df = pd.concat([train, test])

    lines = []

    def out(text=""):
        print(text)
        lines.append(text)

    out("# Backtest V3 report")
    out(f"\nTrain: up to {TRAIN_END}  |  Test: after (untouched by tuning/calibration)")
    out(f"Parameters: k={k}, tau_days={tau}, opponent-adjusted={adjust}")
    out(f"Test matches: {len(test):,}  "
        f"({test['date'].min().date()} -> {test['date'].max().date()})\n")

    # ---- 4. accuracy on the TEST set
    out("## Probability quality on the TEST set (lower Brier/log-loss is better)\n")
    out("| Market | Model | Brier | Log-loss | AUC |")
    out("|---|---|---|---|---|")
    for market, label in (("15", "Over 1.5"), ("25", "Over 2.5")):
        y = test[f"y{market}"]
        for name, col in (("Baseline (league rate)", f"base{market}"),
                          ("V3 raw", f"p{market}_raw"),
                          ("V3 calibrated", f"p{market}_cal")):
            p = test[col]
            auc = "0.500" if name.startswith("Baseline") else f"{roc_auc_score(y, p):.3f}"
            out(f"| {label} | {name} | {brier(p, y):.4f} | {logloss(p, y):.4f} | {auc} |")

    # ---- 5. calibration table (calibrated probs, TEST)
    out("\n## Calibration on the TEST set (calibrated probability vs reality)\n")
    bins = [0, .5, .6, .7, .8, .9, 1.01]
    labels = ["<50%", "50-60%", "60-70%", "70-80%", "80-90%", "90%+"]
    for market, label in (("15", "Over 1.5"), ("25", "Over 2.5")):
        t = test.copy()
        t["bin"] = pd.cut(t[f"p{market}_cal"], bins=bins, labels=labels, right=False)
        g = t.groupby("bin", observed=True).agg(
            matches=(f"y{market}", "size"),
            predicted=(f"p{market}_cal", "mean"),
            actual=(f"y{market}", "mean"))
        out(f"**{label}**\n")
        out("| Bin | Matches | Predicted | Actual |")
        out("|---|---|---|---|")
        for idx, r in g.iterrows():
            out(f"| {idx} | {int(r.matches):,} | {r.predicted:.3f} | {r.actual:.3f} |")
        out()

    # ---- 6. versus the bookmakers (Over 2.5 only: that is what the CSVs contain)
    odds_test = test.dropna(subset=["o_avg", "u_avg"]).copy()
    odds_train = train.dropna(subset=["o_avg", "u_avg"]).copy()
    out("## Versus the bookmakers (Over 2.5, test matches that have odds)\n")
    out(f"Matches with odds: {len(odds_test):,}\n")
    if len(odds_test) > 1000 and len(odds_train) > 1000:
        for frame in (odds_train, odds_test):
            inv_o, inv_u = 1 / frame["o_avg"], 1 / frame["u_avg"]
            frame["mkt"] = inv_o / (inv_o + inv_u)        # remove the margin
        y = odds_test["y25"]
        out("| Predictor | Brier | Log-loss |")
        out("|---|---|---|")
        for name, col in (("Constant baseline", "base25"),
                          ("V3 calibrated", "p25_cal"),
                          ("Bookmaker (avg odds, margin removed)", "mkt")):
            out(f"| {name} | {brier(odds_test[col], y):.4f} | "
                f"{logloss(odds_test[col], y):.4f} |")

        # Does the model add ANYTHING once the market price is known?
        lr = LogisticRegression(C=1e6, max_iter=1000)
        lr.fit(np.column_stack([logit(odds_train["p25_raw"]), logit(odds_train["mkt"])]),
               odds_train["y25"])
        blend = lr.predict_proba(
            np.column_stack([logit(odds_test["p25_raw"]), logit(odds_test["mkt"])]))[:, 1]
        out(f"\nBlend of model + market (fit on train): "
            f"weight on model = {lr.coef_[0][0]:.3f}, "
            f"weight on market = {lr.coef_[0][1]:.3f}; "
            f"test Brier {brier(blend, y):.4f} vs market alone "
            f"{brier(odds_test['mkt'], y):.4f}")
        out("(A model weight near 0 and no Brier gain means the bookmaker's price "
            "already contains everything the model knows.)\n")

        # ---- 7. ROI
        out("## ROI of betting the model's 'edge' (flat 1 unit stakes, test set)\n")
        out("Edge = calibrated probability minus the bookmaker's implied probability. "
            "Avg odds = average across bookmakers (realistic); Max odds = best price "
            "on the market (optimistic).\n")
        out("| Odds | Side | Min edge | Bets | Hit rate | ROI | 95% CI |")
        out("|---|---|---|---|---|---|---|")
        for odds_name, o_col, u_col in (("Avg", "o_avg", "u_avg"),
                                         ("Max", "o_max", "u_max")):
            d = odds_test.dropna(subset=[o_col, u_col])
            over_edge = d["p25_cal"] - 1 / d[o_col]
            under_edge = (1 - d["p25_cal"]) - 1 / d[u_col]
            over_ret = np.where(d["y25"] == 1, d[o_col] - 1, -1.0)
            under_ret = np.where(d["y25"] == 0, d[u_col] - 1, -1.0)
            blind = over_ret
            out(f"| {odds_name} | Over (blind, every match) | - | {len(d):,} | "
                f"{d['y25'].mean():.1%} | {blind.mean():+.2%} | "
                f"+/-{1.96 * blind.std() / math.sqrt(len(d)):.2%} |")
            for side, edge, ret, hit in (
                ("Over", over_edge, over_ret, d["y25"].to_numpy() == 1),
                ("Under", under_edge, under_ret, d["y25"].to_numpy() == 0),
            ):
                for th in EDGE_THRESHOLDS:
                    mask = (edge >= th).to_numpy()
                    n = int(mask.sum())
                    if n < 50:
                        continue
                    r = ret[mask]
                    ci = 1.96 * r.std() / math.sqrt(n)
                    out(f"| {odds_name} | {side} | {th:.0%} | {n:,} | "
                        f"{hit[mask].mean():.1%} | {r.mean():+.2%} | +/-{ci:.2%} |")
        out("\nA strategy is only interesting if ROI is clearly positive AND its "
            "confidence interval stays above zero over thousands of bets.")
    else:
        out("Not enough matches with odds to run the bookmaker comparison.")

    # ---- 8. persist
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    final_cals = {  # production calibration uses ALL data
        "over_1_5_goals": fit_calibrator(df["p15_raw"], df["y15"]),
        "over_2_5_goals": fit_calibrator(df["p25_raw"], df["y25"]),
    }
    (MODEL_DIR / "calibration_v3.json").write_text(json.dumps(final_cals))
    (MODEL_DIR / "params_v3.json").write_text(json.dumps(
        {"k": k, "tau_days": tau, "adjust": adjust, "min_eff": MIN_EFF,
         "trained_through": str(matches[-1]["date"])}, indent=2))

    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    df.assign(split=np.where(df["date"].dt.date <= TRAIN_END, "train", "test")) \
      .round(5).to_csv(RESULTS_FILE, index=False)
    REPORT_FILE.write_text("\n".join(lines), encoding="utf-8")

    print(f"\nSaved: {RESULTS_FILE}\n       {REPORT_FILE}\n       "
          f"{MODEL_DIR / 'calibration_v3.json'}\n       {MODEL_DIR / 'params_v3.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
