"""Backtest V4 - V3 ratings + short-term form + team over/under tendencies,
combined by a regularised logistic model. Honest walk-forward, held-out test.

Run from the project root:   python backtest_v4.py
Writes: data/models/model_v4.json (used by the live app),
        data/historical/backtest_v4_report.md, backtest_v4_results.csv
"""
import json
import math
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from app.services.calibration import apply_calibrator, fit_calibrator
from app.services.features import FEATURE_NAMES, FeatureEngine
from app.services.cross_league import outcome_probs
from app.services.history_loader import load_all_matches

TRAIN_END = date(2022, 6, 30)       # test = everything after
SELECT_END_FOR_POCKETS = (date(2019, 6, 30), date(2022, 6, 30))
MODEL_FILE = Path("data/models/model_v4.json")
OUTCOME_FILE = Path("data/models/model_outcome.json")
RESULTS_FILE = Path("data/historical/backtest_v4_results.csv")
REPORT_FILE = Path("data/historical/backtest_v4_report.md")
LR_C = 0.5


def build_features(matches, params):
    fe = FeatureEngine(slow=params)
    rows, i, n = [], 0, len(matches)
    while i < n:
        j, day = i, matches[i]["day"]
        while j < n and matches[j]["day"] == day:
            j += 1
        batch = matches[i:j]
        for m in batch:                                   # predict first ...
            f = fe.features(m["group"], m["hk"], m["ak"], day, m["date"].month)
            if f is None:
                continue
            goals = m["hg"] + m["ag"]
            f.update(date=m["date"], group=m["group"], home_team=m["home"], away_team=m["away"],
                     home_goals=m["hg"], away_goals=m["ag"], y15=int(goals >= 2), y25=int(goals >= 3),
                     o_avg=m["o_avg"], u_avg=m["u_avg"], o_max=m["o_max"], u_max=m["u_max"],
                     res=0 if m["hg"] > m["ag"] else (1 if m["hg"] == m["ag"] else 2),
                     x_h=m["x12"][0], x_d=m["x12"][1], x_a=m["x12"][2])
            rows.append(f)
        for m in batch:                                   # ... then reveal results
            fe.update(m["group"], m["hk"], m["ak"], day, m["hg"], m["ag"])
        i = j
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df


def fit_logistic(frame, target):
    return make_pipeline(StandardScaler(), LogisticRegression(C=LR_C, max_iter=3000)).fit(
        frame[FEATURE_NAMES], frame[target])


def export_spec(models, trained_through):
    spec = {"features": FEATURE_NAMES, "trained_through": trained_through, "markets": {}}
    for name, pipe in models.items():
        sc, lr = pipe.named_steps["standardscaler"], pipe.named_steps["logisticregression"]
        spec["markets"][name] = {
            "mean": [float(x) for x in sc.mean_], "scale": [float(x) for x in sc.scale_],
            "coef": [float(x) for x in lr.coef_[0]], "intercept": float(lr.intercept_[0])}
    return spec


def outcome_section(df, train, test, out):
    """Home/draw/away model + the win-or-draw (double chance) markets. Returns a
    spec for the model fitted on ALL data (used by the live app)."""
    def fit(frame):
        return make_pipeline(StandardScaler(), LogisticRegression(C=LR_C, max_iter=3000)).fit(
            frame[FEATURE_NAMES], frame["res"])

    def brier3(P, y):
        return float(((P - np.eye(3)[y]) ** 2).sum(1).mean())

    def rps(P, y):
        return float((((np.cumsum(P, 1) - np.cumsum(np.eye(3)[y], 1))[:, :2]) ** 2).sum(1).mean() / 2)

    def row(name, P, y):
        out(f"| {name} | {log_loss(y, np.clip(P, 1e-6, 1), labels=[0, 1, 2]):.4f} | {brier3(P, y):.4f} | {rps(P, y):.4f} |")

    model = fit(train)
    y_te = test["res"].to_numpy()
    freq = np.bincount(train["res"], minlength=3) / len(train)
    P_base = np.tile(freq, (len(test), 1))
    P_pois = np.array([outcome_probs(a, b) for a, b in zip(test.lam_h_s, test.lam_a_s)])
    P_lr = model.predict_proba(test[FEATURE_NAMES])

    out("\n## Match result (home / draw / away) on the TEST set\n")
    out("| Model | Log-loss | Brier | RPS |\n|---|---|---|---|")
    row("Frequency baseline", P_base, y_te)
    row("Poisson from ratings", P_pois, y_te)
    row("Logistic on V4 features (used live)", P_lr, y_te)

    w = test.dropna(subset=["x_h", "x_d", "x_a"]).copy()
    if len(w) > 1000:
        inv = 1 / w[["x_h", "x_d", "x_a"]].to_numpy()
        P_mkt = inv / inv.sum(1, keepdims=True)
        P_w = model.predict_proba(w[FEATURE_NAMES])
        y_w = w["res"].to_numpy()
        out(f"\n**Against the bookmakers' 1X2 odds** ({len(w):,} test matches with odds)\n")
        out("| Predictor | Log-loss | Brier | RPS |\n|---|---|---|---|")
        row("Logistic (used live)", P_w, y_w)
        row("Bookmaker, margin removed", P_mkt, y_w)

        out("\n## Win-or-draw (double chance) on the same matches\n")
        out("| Market | Model Brier | Bookmaker Brier | Happened |\n|---|---|---|---|")
        sets = {"1X (home or draw)": [0, 1], "X2 (away or draw)": [1, 2], "12 (no draw)": [0, 2]}
        for name, idx in sets.items():
            y = np.isin(y_w, idx).astype(float)
            out(f"| {name} | {((P_w[:, idx].sum(1) - y) ** 2).mean():.4f} | "
                f"{((P_mkt[:, idx].sum(1) - y) ** 2).mean():.4f} | {y.mean():.1%} |")

        out("\nCalibration of the model's 1X / X2 probabilities:\n")
        out("| Market | Bin | Matches | Predicted | Actual |\n|---|---|---|---|---|")
        for name, idx in (("1X", [0, 1]), ("X2", [1, 2])):
            p, y = P_w[:, idx].sum(1), np.isin(y_w, idx)
            for lo, hi in ((0, .5), (.5, .6), (.6, .7), (.7, .8), (.8, .9), (.9, 1.01)):
                m = (p >= lo) & (p < hi)
                if m.sum() >= 100:
                    out(f"| {name} | {lo:.0%}-{min(hi, 1):.0%} | {int(m.sum()):,} | {p[m].mean():.3f} | {y[m].mean():.3f} |")

        # ROI with a price derived from the 1X2 odds (how bookmakers build double-chance prices;
        # real double-chance prices carry extra margin, so this is OPTIMISTIC for the bettor).
        H, D, A = w["x_h"].to_numpy(), w["x_d"].to_numpy(), w["x_a"].to_numpy()
        price = {"1X": 1 / (1 / H + 1 / D), "X2": 1 / (1 / D + 1 / A)}
        idxs = {"1X": [0, 1], "X2": [1, 2]}

        def roi(mask, key):
            win = np.isin(y_w, idxs[key])
            r = np.where(win, price[key] - 1, -1.0)[mask]
            n = len(r)
            return n, (r.mean() if n else float("nan")), (1.96 * r.std() / math.sqrt(n) if n > 1 else float("nan")), (win[mask].mean() if n else float("nan"))

        out("\n## ROI of win-or-draw bets (flat stakes; price derived from 1X2 odds, so optimistic)\n")
        out("| Strategy | Bets | Hit rate | ROI | 95% CI |\n|---|---|---|---|---|")
        for key in ("1X", "X2"):
            n, r, ci, h = roi(np.ones(len(w), bool), key)
            out(f"| {key} on every match | {n:,} | {h:.1%} | {r:+.2%} | +/-{ci:.2%} |")
        p1x, px2 = P_w[:, [0, 1]].sum(1), P_w[:, [1, 2]].sum(1)
        best = np.where(p1x >= px2, "1X", "X2")
        rets = np.array([price[k][i] - 1 if y_w[i] in idxs[k] else -1.0 for i, k in enumerate(best)])
        hit = np.array([y_w[i] in idxs[k] for i, k in enumerate(best)])
        out(f"| 'Safest pick' (higher of 1X / X2) | {len(rets):,} | {hit.mean():.1%} | {rets.mean():+.2%} | "
            f"+/-{1.96 * rets.std() / math.sqrt(len(rets)):.2%} |")
        for th in (0.03, 0.05):
            for key, p in (("1X", p1x), ("X2", px2)):
                n, r, ci, h = roi((p - 1 / price[key]) >= th, key)
                if n > 50:
                    out(f"| {key} when model edge >= {th:.0%} | {n:,} | {h:.1%} | {r:+.2%} | +/-{ci:.2%} |")
        out("\nA high hit rate is not profit: short odds mean one loss wipes out several wins.")

    final = fit(df)
    sc, lr = final.named_steps["standardscaler"], final.named_steps["logisticregression"]
    return {"features": FEATURE_NAMES, "mean": [float(x) for x in sc.mean_],
            "scale": [float(x) for x in sc.scale_],
            "coef": [[float(x) for x in row_] for row_ in lr.coef_],
            "intercept": [float(x) for x in lr.intercept_]}


def main():
    try:
        matches = load_all_matches()
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}\nRun from your sports buddy project root.")
        return 1
    params = dict(k=16.0, tau_days=730.0, adjust=False)
    pj = Path("data/models/params_v3.json")
    if pj.exists():
        p = json.loads(pj.read_text())
        params = dict(k=p["k"], tau_days=p["tau_days"], adjust=p["adjust"])
    print(f"Loaded {len(matches):,} matches; building walk-forward features (params {params})...")
    df = build_features(matches, params)
    d = df["date"].dt.date
    train, test = df[d <= TRAIN_END].copy(), df[d > TRAIN_END].copy()
    print(f"train {len(train):,}  test {len(test):,}")

    lines = []
    def out(t=""):
        print(t); lines.append(t)

    def metrics(p, y):
        p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
        return brier_score_loss(y, p), log_loss(y, p), roc_auc_score(y, p)

    out("# Backtest V4 report\n")
    out(f"Train up to {TRAIN_END}; test after (untouched). Test matches: {len(test):,} "
        f"({test['date'].min().date()} -> {test['date'].max().date()})\n")
    out("## Probability quality on the TEST set\n")
    out("| Market | Model | Brier | Log-loss | AUC |")
    out("|---|---|---|---|---|")
    models = {}
    for tag, label, name in (("15", "Over 1.5", "over_1_5_goals"), ("25", "Over 2.5", "over_2_5_goals")):
        y_tr, y_te = train[f"y{tag}"], test[f"y{tag}"]
        cal = fit_calibrator(train[f"p{tag}_raw"], y_tr)
        test[f"p{tag}_v3"] = [apply_calibrator(cal, p) for p in test[f"p{tag}_raw"]]
        pipe = fit_logistic(train, f"y{tag}")
        models[name] = pipe
        test[f"p{tag}_v4"] = pipe.predict_proba(test[FEATURE_NAMES])[:, 1]
        for mname, col in (("League-rate baseline", f"lg_o{tag}"), ("V3 calibrated", f"p{tag}_v3"),
                           ("V4", f"p{tag}_v4")):
            b, l, a = metrics(test[col], y_te)
            auc = "-" if mname.startswith("League") else f"{a:.3f}"
            out(f"| {label} | {mname} | {b:.4f} | {l:.4f} | {auc} |")

    out("\n## Calibration of V4 on the TEST set\n")
    bins, labels = [0, .5, .6, .7, .8, .9, 1.01], ["<50%", "50-60%", "60-70%", "70-80%", "80-90%", "90%+"]
    for tag, label in (("15", "Over 1.5"), ("25", "Over 2.5")):
        t = test.copy()
        t["bin"] = pd.cut(t[f"p{tag}_v4"], bins=bins, labels=labels, right=False)
        g = t.groupby("bin", observed=True).agg(n=(f"y{tag}", "size"), pred=(f"p{tag}_v4", "mean"),
                                                act=(f"y{tag}", "mean"))
        out(f"**{label}**\n\n| Bin | Matches | Predicted | Actual |\n|---|---|---|---|")
        for idx, r in g.iterrows():
            out(f"| {idx} | {int(r.n):,} | {r.pred:.3f} | {r.act:.3f} |")
        out()

    # ---- versus the bookmakers (Over 2.5)
    od_te = test.dropna(subset=["o_avg", "u_avg"]).copy()
    tr_od = train.dropna(subset=["o_avg", "u_avg"]).copy()
    out("## Versus the bookmakers (Over 2.5, test matches with odds)\n")
    out(f"Matches with odds: {len(od_te):,}\n")
    mk = lambda f: (1 / f.o_avg) / ((1 / f.o_avg) + (1 / f.u_avg))
    od_te["mkt"], tr_od["mkt"] = mk(od_te), mk(tr_od)
    out("| Predictor | Brier | Log-loss | AUC |\n|---|---|---|---|")
    for nm, col in (("V3 calibrated", "p25_v3"), ("V4", "p25_v4"), ("Bookmaker (margin removed)", "mkt")):
        b, l, a = metrics(od_te[col], od_te.y25)
        out(f"| {nm} | {b:.4f} | {l:.4f} | {a:.3f} |")
    lg = lambda p: np.log(np.clip(p, 1e-4, 1 - 1e-4) / (1 - np.clip(p, 1e-4, 1 - 1e-4)))
    tr_od["p25_v4"] = models["over_2_5_goals"].predict_proba(tr_od[FEATURE_NAMES])[:, 1]
    blend = LogisticRegression(C=1e6, max_iter=1000).fit(np.c_[lg(tr_od.p25_v4), lg(tr_od.mkt)], tr_od.y25)
    pb = blend.predict_proba(np.c_[lg(od_te.p25_v4), lg(od_te.mkt)])[:, 1]
    out(f"\nBlend V4 + market (fit on train): weight on V4 {blend.coef_[0][0]:.3f}, on market "
        f"{blend.coef_[0][1]:.3f}; test Brier {brier_score_loss(od_te.y25, pb):.4f} vs market alone "
        f"{brier_score_loss(od_te.y25, od_te.mkt):.4f}.")
    out("(No Brier gain over the market alone => the bookmaker price already contains what V4 knows.)\n")

    # ---- ROI
    out("## ROI of betting V4's 'edge' (flat stakes, test set)\n")
    out("| Odds | Side | Min edge | Bets | Hit rate | ROI | 95% CI |\n|---|---|---|---|---|---|---|")
    for oname, oc, uc in (("Avg", "o_avg", "u_avg"), ("Max", "o_max", "u_max")):
        dd = od_te.dropna(subset=[oc, uc])
        for side, edge, ret, hit in (
            ("Over", dd.p25_v4 - 1 / dd[oc], np.where(dd.y25 == 1, dd[oc] - 1, -1.0), dd.y25.to_numpy() == 1),
            ("Under", (1 - dd.p25_v4) - 1 / dd[uc], np.where(dd.y25 == 0, dd[uc] - 1, -1.0), dd.y25.to_numpy() == 0),
        ):
            for th in (0.0, 0.03, 0.05, 0.10):
                m = (edge >= th).to_numpy()
                nn = int(m.sum())
                if nn < 50:
                    continue
                r = ret[m]
                out(f"| {oname} | {side} | {th:.0%} | {nn:,} | {hit[m].mean():.1%} | {r.mean():+.2%} | "
                    f"+/-{1.96 * r.std() / math.sqrt(nn):.2%} |")

    outcome_spec = outcome_section(df, train, test, out)

    # ---- pocket search: choose on a selection period, confirm on test
    sel_lo, sel_hi = SELECT_END_FOR_POCKETS
    fit_p = df[df["date"].dt.date <= sel_lo]
    pipe_sel = fit_logistic(fit_p, "y25")
    sel = df[(df["date"].dt.date > sel_lo) & (df["date"].dt.date <= sel_hi)].dropna(subset=["o_avg", "u_avg"]).copy()
    tst = df[df["date"].dt.date > sel_hi].dropna(subset=["o_avg", "u_avg"]).copy()
    sel["p"] = pipe_sel.predict_proba(sel[FEATURE_NAMES])[:, 1]
    tst["p"] = pipe_sel.predict_proba(tst[FEATURE_NAMES])[:, 1]

    def roi(f, side, th=0.03):
        if side == "Over":
            e, r = f.p - 1 / f.o_avg, np.where(f.y25 == 1, f.o_avg - 1, -1.0)
        else:
            e, r = (1 - f.p) - 1 / f.u_avg, np.where(f.y25 == 0, f.u_avg - 1, -1.0)
        m = (e >= th).to_numpy()
        return int(m.sum()), (r[m].mean() if m.any() else float("nan"))
    combos = picked = confirmed = 0
    for g in sorted(set(sel.group) & set(tst.group)):
        for side in ("Over", "Under"):
            combos += 1
            ns, rs = roi(sel[sel.group == g], side)
            if ns >= 150 and rs > 0:
                picked += 1
                nt, rt = roi(tst[tst.group == g], side)
                confirmed += int(nt >= 100 and rt > 0)
    out("\n## Is there a league where it works? (pick on 2019-22, confirm on 2022+)\n")
    out(f"League/side combinations tested: {combos}; looked profitable in the selection period: "
        f"{picked}; still profitable on the untouched test period: {confirmed}.")
    out("Combos that look good by chance are expected; only ones that confirm out of sample matter.")

    # ---- persist (production model is fitted on ALL data)
    MODEL_FILE.parent.mkdir(parents=True, exist_ok=True)
    final = {name: fit_logistic(df, f"y{tag}") for name, tag in
             (("over_1_5_goals", "15"), ("over_2_5_goals", "25"))}
    MODEL_FILE.write_text(json.dumps(export_spec(final, str(matches[-1]["date"]))))
    OUTCOME_FILE.write_text(json.dumps(outcome_spec))
    df.round(5).to_csv(RESULTS_FILE, index=False)
    REPORT_FILE.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nSaved {MODEL_FILE}, {OUTCOME_FILE}, {REPORT_FILE}, {RESULTS_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
