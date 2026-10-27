"""V3 team-strength engine (walk-forward, no look-ahead).

For every team in a competition we keep time-decayed, shrunk attack and
defence ratings:

    attack  = (decayed goals scored   + k * g) / (decayed matches + k) / g
    defence = (decayed goals conceded + k * g) / (decayed matches + k) / g

where g is the league's average goals per team per match. `k` pulls small
samples toward the league average (this is what V1/V2 lacked: five-match
averages are extremely noisy). Ratings carry over between seasons and decay
with a half-life controlled by `tau_days`.

With adjust=True each observed score is first divided by the opponent's
rating and the venue factor, so scoring against weak defences counts for less.
"""
import math

HOME_PRIOR, AWAY_PRIOR, LEAGUE_PRIOR_WEIGHT = 1.45, 1.15, 30.0
RATING_MIN, RATING_MAX = 0.35, 3.0
LAMBDA_MIN, LAMBDA_MAX = 0.15, 4.5


def _clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


class RatingEngine:
    def __init__(self, k=8.0, tau_days=365.0, adjust=True, min_eff=6.0):
        self.k = float(k)
        self.tau = float(tau_days)
        self.adjust = bool(adjust)
        self.min_eff = float(min_eff)
        self.league = {}   # group -> [home_goals, away_goals, matches]
        self.team = {}     # (group, key) -> [att_sum, def_sum, weight, last_day]

    # ---------- league level ----------
    def league_means(self, group):
        hs, as_, n = self.league.get(group, (0.0, 0.0, 0))
        w = LEAGUE_PRIOR_WEIGHT
        mu_h = (hs + w * HOME_PRIOR) / (n + w)
        mu_a = (as_ + w * AWAY_PRIOR) / (n + w)
        return mu_h, mu_a, (mu_h + mu_a) / 2.0

    # ---------- team level ----------
    def _decayed(self, group, key, day):
        state = self.team.get((group, key))
        if state is None:
            return 0.0, 0.0, 0.0
        f = math.exp(-max(0, day - state[3]) / self.tau)
        return state[0] * f, state[1] * f, state[2] * f

    def ratings(self, group, key, day, g):
        att_sum, def_sum, w = self._decayed(group, key, day)
        att = (att_sum + self.k * g) / (w + self.k) / g
        dfn = (def_sum + self.k * g) / (w + self.k) / g
        return (_clamp(att, RATING_MIN, RATING_MAX),
                _clamp(dfn, RATING_MIN, RATING_MAX), w)

    def predict(self, group, home_key, away_key, day):
        """Return (lambda_home, lambda_away, eff_matches_home, eff_matches_away)
        or None when either side has too little history."""
        mu_h, mu_a, g = self.league_means(group)
        att_h, dfn_h, w_h = self.ratings(group, home_key, day, g)
        att_a, dfn_a, w_a = self.ratings(group, away_key, day, g)
        if w_h < self.min_eff or w_a < self.min_eff:
            return None
        lam_h = _clamp(mu_h * att_h * dfn_a, LAMBDA_MIN, LAMBDA_MAX)
        lam_a = _clamp(mu_a * att_a * dfn_h, LAMBDA_MIN, LAMBDA_MAX)
        return lam_h, lam_a, w_h, w_a

    def update(self, group, home_key, away_key, day, hg, ag):
        mu_h, mu_a, g = self.league_means(group)
        att_h, dfn_h, _ = self.ratings(group, home_key, day, g)
        att_a, dfn_a, _ = self.ratings(group, away_key, day, g)

        if self.adjust:
            h_for = hg / (dfn_a * mu_h / g)
            h_against = ag / (att_a * mu_a / g)
            a_for = ag / (dfn_h * mu_a / g)
            a_against = hg / (att_h * mu_h / g)
        else:
            h_for, h_against, a_for, a_against = hg, ag, ag, hg

        for key, gf, ga in ((home_key, h_for, h_against),
                            (away_key, a_for, a_against)):
            att_sum, def_sum, w = self._decayed(group, key, day)
            self.team[(group, key)] = [att_sum + gf, def_sum + ga, w + 1.0, day]

        stats = self.league.setdefault(group, [0.0, 0.0, 0])
        stats[0] += hg
        stats[1] += ag
        stats[2] += 1


def poisson_over_probabilities(lam_total: float) -> tuple[float, float]:
    """P(total goals >= 2) and P(total goals >= 3) for Poisson(lam_total)."""
    e = math.exp(-lam_total)
    p_le1 = e * (1.0 + lam_total)
    p_le2 = p_le1 + e * lam_total ** 2 / 2.0
    return 1.0 - p_le1, 1.0 - p_le2
