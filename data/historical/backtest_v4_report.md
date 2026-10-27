# Backtest V4 report

Train up to 2022-06-30; test after (untouched). Test matches: 51,122 (2022-07-01 -> 2026-10-23)

## Probability quality on the TEST set

| Market | Model | Brier | Log-loss | AUC |
|---|---|---|---|---|
| Over 1.5 | League-rate baseline | 0.1845 | 0.5550 | - |
| Over 1.5 | V3 calibrated | 0.1829 | 0.5505 | 0.590 |
| Over 1.5 | V4 | 0.1826 | 0.5498 | 0.593 |
| Over 2.5 | League-rate baseline | 0.2472 | 0.6875 | - |
| Over 2.5 | V3 calibrated | 0.2437 | 0.6804 | 0.590 |
| Over 2.5 | V4 | 0.2430 | 0.6789 | 0.594 |

## Calibration of V4 on the TEST set

**Over 1.5**

| Bin | Matches | Predicted | Actual |
|---|---|---|---|
| 50-60% | 278 | 0.587 | 0.612 |
| 60-70% | 10,946 | 0.669 | 0.669 |
| 70-80% | 30,691 | 0.749 | 0.759 |
| 80-90% | 9,056 | 0.827 | 0.833 |
| 90%+ | 151 | 0.915 | 0.914 |

**Over 2.5**

| Bin | Matches | Predicted | Actual |
|---|---|---|---|
| <50% | 24,879 | 0.443 | 0.444 |
| 50-60% | 20,451 | 0.544 | 0.558 |
| 60-70% | 5,375 | 0.633 | 0.657 |
| 70-80% | 409 | 0.731 | 0.733 |
| 80-90% | 8 | 0.818 | 0.875 |

## Versus the bookmakers (Over 2.5, test matches with odds)

Matches with odds: 31,326

| Predictor | Brier | Log-loss | AUC |
|---|---|---|---|
| V3 calibrated | 0.2446 | 0.6821 | 0.583 |
| V4 | 0.2441 | 0.6813 | 0.585 |
| Bookmaker (margin removed) | 0.2419 | 0.6766 | 0.601 |

Blend V4 + market (fit on train): weight on V4 -0.073, on market 1.155; test Brier 0.2417 vs market alone 0.2419.
(No Brier gain over the market alone => the bookmaker price already contains what V4 knows.)

## ROI of betting V4's 'edge' (flat stakes, test set)

| Odds | Side | Min edge | Bets | Hit rate | ROI | 95% CI |
|---|---|---|---|---|---|---|
| Avg | Over | 0% | 5,913 | 45.0% | -7.41% | +/-2.67% |
| Avg | Over | 3% | 1,722 | 42.5% | -8.22% | +/-5.16% |
| Avg | Over | 5% | 621 | 37.5% | -14.86% | +/-8.83% |
| Avg | Under | 0% | 7,574 | 42.1% | -9.21% | +/-2.47% |
| Avg | Under | 3% | 2,667 | 37.9% | -11.90% | +/-4.40% |
| Avg | Under | 5% | 1,260 | 37.1% | -9.98% | +/-6.66% |
| Avg | Under | 10% | 144 | 28.5% | -24.66% | +/-20.05% |
| Max | Over | 0% | 10,555 | 46.2% | -3.76% | +/-2.03% |
| Max | Over | 3% | 3,848 | 45.0% | -2.46% | +/-3.49% |
| Max | Over | 5% | 1,628 | 42.2% | -5.02% | +/-5.53% |
| Max | Over | 10% | 112 | 42.0% | +2.96% | +/-22.90% |
| Max | Under | 0% | 12,379 | 44.1% | -5.03% | +/-1.95% |
| Max | Under | 3% | 5,187 | 40.4% | -6.80% | +/-3.18% |
| Max | Under | 5% | 2,510 | 38.2% | -7.25% | +/-4.77% |
| Max | Under | 10% | 357 | 36.1% | -5.25% | +/-13.44% |

## Match result (home / draw / away) on the TEST set

| Model | Log-loss | Brier | RPS |
|---|---|---|---|
| Frequency baseline | 1.0737 | 0.6495 | 0.2280 |
| Poisson from ratings | 1.0222 | 0.6126 | 0.2102 |
| Logistic on V4 features (used live) | 1.0174 | 0.6096 | 0.2089 |

**Against the bookmakers' 1X2 odds** (31,327 test matches with odds)

| Predictor | Log-loss | Brier | RPS |
|---|---|---|---|
| Logistic (used live) | 1.0119 | 0.6060 | 0.2075 |
| Bookmaker, margin removed | 0.9982 | 0.5966 | 0.2031 |

## Win-or-draw (double chance) on the same matches

| Market | Model Brier | Bookmaker Brier | Happened |
|---|---|---|---|
| 1X (home or draw) | 0.1927 | 0.1886 | 69.6% |
| X2 (away or draw) | 0.2223 | 0.2175 | 56.5% |
| 12 (no draw) | 0.1910 | 0.1905 | 73.9% |

Calibration of the model's 1X / X2 probabilities:

| Market | Bin | Matches | Predicted | Actual |
|---|---|---|---|---|
| 1X | 0%-50% | 2,811 | 0.403 | 0.397 |
| 1X | 50%-60% | 3,893 | 0.557 | 0.558 |
| 1X | 60%-70% | 8,433 | 0.655 | 0.670 |
| 1X | 70%-80% | 10,098 | 0.748 | 0.749 |
| 1X | 80%-90% | 4,800 | 0.840 | 0.846 |
| 1X | 90%-100% | 1,292 | 0.932 | 0.952 |
| X2 | 0%-50% | 9,110 | 0.394 | 0.383 |
| X2 | 50%-60% | 9,076 | 0.552 | 0.556 |
| X2 | 60%-70% | 7,945 | 0.645 | 0.643 |
| X2 | 70%-80% | 3,643 | 0.742 | 0.744 |
| X2 | 80%-90% | 1,327 | 0.841 | 0.859 |
| X2 | 90%-100% | 226 | 0.918 | 0.903 |

## ROI of win-or-draw bets (flat stakes; price derived from 1X2 odds, so optimistic)

| Strategy | Bets | Hit rate | ROI | 95% CI |
|---|---|---|---|---|
| 1X on every match | 31,327 | 69.6% | -5.93% | +/-0.75% |
| X2 on every match | 31,327 | 56.5% | -8.15% | +/-0.99% |
| 'Safest pick' (higher of 1X / X2) | 31,327 | 75.6% | -4.88% | +/-0.62% |
| 1X when model edge >= 3% | 2,913 | 52.9% | -10.45% | +/-3.35% |
| X2 when model edge >= 3% | 4,059 | 42.9% | -12.49% | +/-3.38% |
| 1X when model edge >= 5% | 1,712 | 50.8% | -10.14% | +/-4.59% |
| X2 when model edge >= 5% | 2,428 | 41.8% | -11.81% | +/-4.47% |

A high hit rate is not profit: short odds mean one loss wipes out several wins.

## Is there a league where it works? (pick on 2019-22, confirm on 2022+)

League/side combinations tested: 44; looked profitable in the selection period: 1; still profitable on the untouched test period: 0.
Combos that look good by chance are expected; only ones that confirm out of sample matter.