# Backtest V3 report

Train: up to 2022-06-30  |  Test: after (untouched by tuning/calibration)
Parameters: k=16.0, tau_days=730.0, opponent-adjusted=False
Test matches: 51,092  (2022-07-01 -> 2026-10-17)

## Probability quality on the TEST set (lower Brier/log-loss is better)

| Market | Model | Brier | Log-loss | AUC |
|---|---|---|---|---|
| Over 1.5 | Baseline (league rate) | 0.1846 | 0.5552 | 0.500 |
| Over 1.5 | V3 raw | 0.1832 | 0.5510 | 0.590 |
| Over 1.5 | V3 calibrated | 0.1829 | 0.5506 | 0.590 |
| Over 2.5 | Baseline (league rate) | 0.2472 | 0.6875 | 0.500 |
| Over 2.5 | V3 raw | 0.2439 | 0.6808 | 0.590 |
| Over 2.5 | V3 calibrated | 0.2437 | 0.6804 | 0.590 |

## Calibration on the TEST set (calibrated probability vs reality)

**Over 1.5**

| Bin | Matches | Predicted | Actual |
|---|---|---|---|
| 60-70% | 10,246 | 0.671 | 0.669 |
| 70-80% | 31,880 | 0.748 | 0.756 |
| 80-90% | 8,966 | 0.824 | 0.834 |

**Over 2.5**

| Bin | Matches | Predicted | Actual |
|---|---|---|---|
| <50% | 26,319 | 0.447 | 0.452 |
| 50-60% | 19,682 | 0.548 | 0.560 |
| 60-70% | 5,091 | 0.628 | 0.658 |

## Versus the bookmakers (Over 2.5, test matches that have odds)

Matches with odds: 31,326

| Predictor | Brier | Log-loss |
|---|---|---|
| Constant baseline | 0.2484 | 0.6899 |
| V3 calibrated | 0.2446 | 0.6821 |
| Bookmaker (avg odds, margin removed) | 0.2419 | 0.6766 |

Blend of model + market (fit on train): weight on model = -0.083, weight on market = 1.174; test Brier 0.2418 vs market alone 0.2419
(A model weight near 0 and no Brier gain means the bookmaker's price already contains everything the model knows.)

## ROI of betting the model's 'edge' (flat 1 unit stakes, test set)

Edge = calibrated probability minus the bookmaker's implied probability. Avg odds = average across bookmakers (realistic); Max odds = best price on the market (optimistic).

| Odds | Side | Min edge | Bets | Hit rate | ROI | 95% CI |
|---|---|---|---|---|---|---|
| Avg | Over (blind, every match) | - | 31,326 | 51.5% | -5.16% | +/-1.04% |
| Avg | Over | 0% | 7,034 | 44.5% | -7.56% | +/-2.46% |
| Avg | Over | 3% | 2,469 | 42.8% | -7.12% | +/-4.32% |
| Avg | Over | 5% | 996 | 39.6% | -11.19% | +/-6.94% |
| Avg | Under | 0% | 8,306 | 41.0% | -9.92% | +/-2.40% |
| Avg | Under | 3% | 3,582 | 37.6% | -10.14% | +/-3.92% |
| Avg | Under | 5% | 1,899 | 35.5% | -10.49% | +/-5.63% |
| Avg | Under | 10% | 309 | 31.1% | -11.17% | +/-15.37% |
| Max | Over (blind, every match) | - | 31,326 | 51.5% | -1.77% | +/-1.08% |
| Max | Over | 0% | 11,283 | 46.6% | -1.92% | +/-1.98% |
| Max | Over | 3% | 4,913 | 44.1% | -3.15% | +/-3.11% |
| Max | Over | 5% | 2,351 | 42.8% | -3.21% | +/-4.62% |
| Max | Over | 10% | 184 | 37.0% | -9.86% | +/-17.31% |
| Max | Under | 0% | 12,551 | 43.2% | -5.26% | +/-1.96% |
| Max | Under | 3% | 6,178 | 39.4% | -7.16% | +/-2.98% |
| Max | Under | 5% | 3,386 | 37.9% | -5.09% | +/-4.26% |
| Max | Under | 10% | 606 | 33.0% | -2.77% | +/-11.57% |

A strategy is only interesting if ROI is clearly positive AND its confidence interval stays above zero over thousands of bets.