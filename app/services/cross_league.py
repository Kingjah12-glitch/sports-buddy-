"""Cross-league (e.g. Champions League) estimates.

Domestic ratings are only comparable inside one league. For a match between
teams from different leagues we therefore:
  1. take each team's attack/defence rating relative to ITS OWN league,
  2. scale goals to the average of the two leagues' goal levels,
  3. shift the two expected-goals figures (keeping their ratio structure) until
     the implied home-win minus away-win probability equals the one supplied
     from outside (feed win probabilities or de-vigged bookmaker 1X2 odds).
The over/under probabilities then follow from the adjusted total.
Validated on domestic matches (using their real 1X2 odds): as good as the
ratings-only model (Over 2.5 Brier 0.2442 vs 0.2446) - but NOT validated on
Champions League matches themselves, so treat results as rough.
"""
import math

MAX_GOALS = 11


def _pmf(lam: float):
    p = [math.exp(-lam)]
    for k in range(1, MAX_GOALS):
        p.append(p[-1] * lam / k)
    return p


def win_minus_loss(lam_h: float, lam_a: float) -> float:
    """P(home win) - P(away win) under independent Poisson goals."""
    ph, pa = _pmf(lam_h), _pmf(lam_a)
    cum_a = cum_h = 0.0
    p_home = p_away = 0.0
    for i in range(MAX_GOALS):
        p_home += ph[i] * cum_a          # home scores i, away scored fewer
        p_away += pa[i] * cum_h
        cum_a += pa[i]
        cum_h += ph[i]
    return p_home - p_away


def fit_supremacy(lam_h0: float, lam_a0: float, target: float):
    """Scale (lam_h0, lam_a0) by exp(+-theta/2) so win_minus_loss == target."""
    lo, hi = -4.0, 4.0
    for _ in range(40):
        mid = (lo + hi) / 2
        diff = win_minus_loss(lam_h0 * math.exp(mid / 2), lam_a0 * math.exp(-mid / 2))
        lo, hi = (mid, hi) if diff < target else (lo, mid)
    theta = (lo + hi) / 2
    lam_h = min(5.0, max(0.1, lam_h0 * math.exp(theta / 2)))
    lam_a = min(5.0, max(0.1, lam_a0 * math.exp(-theta / 2)))
    return lam_h, lam_a


def devig_percentages(p_home, p_draw, p_away):
    total = p_home + p_draw + p_away
    return p_home / total, p_draw / total, p_away / total


def devig_odds(odds_home, odds_draw, odds_away):
    inv = [1 / odds_home, 1 / odds_draw, 1 / odds_away]
    total = sum(inv)
    return tuple(x / total for x in inv)


def outcome_probs(lam_h: float, lam_a: float):
    """(P(home win), P(draw), P(away win)) under independent Poisson goals."""
    ph, pa = _pmf(lam_h), _pmf(lam_a)
    home = draw = away = 0.0
    for i in range(MAX_GOALS):
        for j in range(MAX_GOALS):
            p = ph[i] * pa[j]
            if i > j:
                home += p
            elif i == j:
                draw += p
            else:
                away += p
    total = home + draw + away
    return home / total, draw / total, away / total
