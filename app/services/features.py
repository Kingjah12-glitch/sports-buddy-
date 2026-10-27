"""V4 feature engine: everything the model knows about a match BEFORE kickoff.

Two rating engines (slow = long memory, fast = recent form), decayed per-team
over-1.5/over-2.5 tendencies, and league-level goal/over rates.
"""
import math

from app.services.ratings import RatingEngine, poisson_over_probabilities

FEATURE_NAMES = [
    "lam_h_s", "lam_a_s", "lam_tot_s", "lam_h_f", "lam_a_f", "lam_tot_f",
    "p15_raw", "p25_raw", "w_min", "mu_h", "mu_a",
    "lg_o15", "lg_o25", "th_o15", "ta_o15", "th_o25", "ta_o25",
    "att_h", "dfn_h", "att_a", "dfn_a", "month_sin", "month_cos",
]
OVER_TAU_DAYS = 365.0
OVER_PRIOR_WEIGHT = 12.0


class FeatureEngine:
    def __init__(self, slow=None, fast=None, min_eff=6.0):
        self.slow = RatingEngine(**(slow or dict(k=16.0, tau_days=730.0, adjust=False)),
                                 min_eff=min_eff)
        self.fast = RatingEngine(**(fast or dict(k=8.0, tau_days=120.0, adjust=False)),
                                 min_eff=0.0)
        self.over = {}          # (group, team) -> [o15, o25, weight, last_day]
        self.league_over = {}   # group -> [n, o15, o25]

    # ---------------------------------------------------------- helpers
    def _team_over(self, group, key, day):
        s = self.over.get((group, key))
        if s is None:
            return 0.0, 0.0, 0.0
        f = math.exp(-max(0, day - s[3]) / OVER_TAU_DAYS)
        return s[0] * f, s[1] * f, s[2] * f

    def _league_rates(self, group):
        n, o15, o25 = self.league_over.get(group, (0, 0, 0))
        w = 30.0
        return (o15 + w * 0.745) / (n + w), (o25 + w * 0.50) / (n + w)

    # ---------------------------------------------------------- public
    def features(self, group, hk, ak, day, month):
        slow = self.slow.predict(group, hk, ak, day)
        if slow is None:
            return None
        lam_h_s, lam_a_s, w_h, w_a = slow
        lam_h_f, lam_a_f, _, _ = self.fast.predict(group, hk, ak, day)
        p15, p25 = poisson_over_probabilities(lam_h_s + lam_a_s)
        mu_h, mu_a, g = self.slow.league_means(group)
        att_h, dfn_h, _ = self.slow.ratings(group, hk, day, g)
        att_a, dfn_a, _ = self.slow.ratings(group, ak, day, g)
        lg15, lg25 = self._league_rates(group)

        def rate(key, idx, prior):
            o15, o25, w = self._team_over(group, key, day)
            val = o15 if idx == 0 else o25
            return (val + OVER_PRIOR_WEIGHT * prior) / (w + OVER_PRIOR_WEIGHT)

        return {
            "lam_h_s": lam_h_s, "lam_a_s": lam_a_s, "lam_tot_s": lam_h_s + lam_a_s,
            "lam_h_f": lam_h_f, "lam_a_f": lam_a_f, "lam_tot_f": lam_h_f + lam_a_f,
            "p15_raw": p15, "p25_raw": p25, "w_min": min(w_h, w_a),
            "mu_h": mu_h, "mu_a": mu_a, "lg_o15": lg15, "lg_o25": lg25,
            "th_o15": rate(hk, 0, lg15), "ta_o15": rate(ak, 0, lg15),
            "th_o25": rate(hk, 1, lg25), "ta_o25": rate(ak, 1, lg25),
            "att_h": att_h, "dfn_h": dfn_h, "att_a": att_a, "dfn_a": dfn_a,
            "month_sin": math.sin(2 * math.pi * month / 12),
            "month_cos": math.cos(2 * math.pi * month / 12),
        }

    def update(self, group, hk, ak, day, hg, ag):
        self.slow.update(group, hk, ak, day, hg, ag)
        self.fast.update(group, hk, ak, day, hg, ag)
        o15, o25 = float(hg + ag >= 2), float(hg + ag >= 3)
        for key in (hk, ak):
            s0, s1, w = self._team_over(group, key, day)
            self.over[(group, key)] = [s0 + o15, s1 + o25, w + 1.0, day]
        st = self.league_over.setdefault(group, [0, 0, 0])
        st[0] += 1
        st[1] += o15
        st[2] += o25
