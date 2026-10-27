"""Builds (once, lazily) the V3 rating state from the local CSV history and
answers 'what are the expected goals for Home vs Away?' for live fixtures."""
import difflib
import json
import logging
from datetime import date
import threading
from pathlib import Path

from app.services.cross_league import fit_supremacy, outcome_probs
from app.services.features import FeatureEngine
from app.services.history_loader import PROJECT_ROOT, load_all_matches
from app.services.market_analyzer_v3 import analyze_match_v3
from app.services.market_analyzer_v4 import analyze_match_v4
from app.services.market_options import attach_outcome_markets
from app.services.model_v4 import load_model, load_outcome_model
from app.services.names import normalize_name, resolve_key

log = logging.getLogger("sports_buddy")
MODEL_DIR = PROJECT_ROOT / "data" / "models"

DEFAULT_PARAMS = {"k": 16.0, "tau_days": 730.0, "adjust": False, "min_eff": 6.0}

# Live predictions accept teams with as little as ~3 effective matches (newly promoted sides).
# Backtest on 807 such matches (2022+): unbiased (2.67 goals predicted vs 2.71 actual) and no worse
# than teams with more history. Such matches are flagged data_quality=LOW.
LIVE_MIN_EFF = 3.0
MODEL_TRAINED_MIN_W = 6.0      # w_min range the V4 model was trained on


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


class RatingsState:
    def __init__(self):
        params = {**DEFAULT_PARAMS, **(_load_json(MODEL_DIR / "params_v3.json") or {})}
        self.params = params
        self.calibrators = _load_json(MODEL_DIR / "calibration_v3.json") or {}
        self.model = load_model(MODEL_DIR / "model_v4.json")     # None -> fall back to V3
        self.outcome_model = load_outcome_model(MODEL_DIR / "model_outcome.json")   # None -> Poisson 1X2
        self.fe = FeatureEngine(
            slow=dict(k=params["k"], tau_days=params["tau_days"], adjust=params["adjust"]),
            min_eff=min(params["min_eff"], LIVE_MIN_EFF))
        self.engine = self.fe.slow

        self.teams_by_group = {}     # group -> set(team keys)
        self.last_day = {}           # group -> last match ordinal
        self.last_date = None
        for m in load_all_matches():
            self.fe.update(m["group"], m["hk"], m["ak"], m["day"], m["hg"], m["ag"])
            teams = self.teams_by_group.setdefault(m["group"], set())
            teams.add(m["hk"])
            teams.add(m["ak"])
            self.last_day[m["group"]] = m["day"]
            self.last_date = m["date"]
        log.info("Ratings ready: %d competitions, data through %s",
                 len(self.teams_by_group), self.last_date)

    # ------------------------------------------------------------ name matching
    def _resolve(self, key, groups):
        """Exact normalised match first, then token/fuzzy matching per competition."""
        for group in groups:
            found = resolve_key(key, self.teams_by_group[group])
            if found:
                return group, found
        return None

    LEAGUE_ALIASES = {"major league soccer": "mls", "primera division": "la liga",
                      "primera a": "serie a", "2 bundesliga": "bundesliga 2",
                      "liga i": "superliga", "liga 1": "superliga",
                      "segunda division": "segunda", "super lig": "super lig"}

    def covered_groups(self, country, league_name):
        """Competitions in the CSV history that match a provider's country+league
        (empty list = not covered). Country must match; the league name is then
        compared with containment in either direction."""
        flat = lambda t: normalize_name(t).replace(" ", "") if t else ""
        c = flat(country)
        league = flat(self.LEAGUE_ALIASES.get(normalize_name(league_name or ""), league_name))
        if not c:
            return []
        out, exact = [], []
        for group in self.teams_by_group:
            g = flat(group.replace("_", " "))
            if not g.startswith(c):
                continue
            suffix = g[len(c):]
            if not league:
                out.append(group)
            elif suffix and suffix == league:
                exact.append(group)
            elif suffix and (league in g or suffix in league):
                out.append(group)
        return exact or out          # an exact league-name match beats looser containment

    def _hint_groups(self, country, league_name):
        strict = self.covered_groups(country, league_name)
        return strict or list(self.teams_by_group)

    def predict_fixture(self, home_name, away_name, fixture_date: date,
                        country=None, league_name=None):
        hk, ak = normalize_name(home_name), normalize_name(away_name)
        groups = self._hint_groups(country, league_name)

        candidates = []
        for pool in (groups, list(self.teams_by_group)):
            for group in pool:
                h = self._resolve(hk, [group])
                a = self._resolve(ak, [group])
                if h and a:
                    candidates.append((group, h[1], a[1]))
            if candidates:
                break
        if not candidates:
            return None

        # Prefer the competition most recently active in the data.
        candidates.sort(key=lambda c: self.last_day.get(c[0], 0), reverse=True)
        group, home_key, away_key = candidates[0]
        day = fixture_date.toordinal()
        feats = self.fe.features(group, home_key, away_key, day, fixture_date.month)
        if feats is None:
            return None
        feats["w_min"] = max(feats["w_min"], MODEL_TRAINED_MIN_W)   # stay inside the trained range
        _, _, w_h, w_a = self.fe.slow.predict(group, home_key, away_key, day)
        return {
            "competition_file_group": group,
            "matched_home": home_key,
            "matched_away": away_key,
            "lam_home": feats["lam_h_s"], "lam_away": feats["lam_a_s"],
            "eff_home": round(w_h, 1), "eff_away": round(w_a, 1),
            "features": feats,
        }

    # ------------------------------------------------------------ cross-league
    def find_team(self, name, day):
        """(group, key, effective_matches) of the competition where this club is
        currently most active in the CSV history, or None."""
        query = normalize_name(name)
        best = None
        for group, teams in self.teams_by_group.items():
            key = resolve_key(query, teams)
            if not key:
                continue
            _, _, g = self.fe.slow.league_means(group)
            _, _, w = self.fe.slow.ratings(group, key, day, g)
            if best is None or w > best[2]:
                best = (group, key, w)
        return best if best and best[2] >= 3 else None

    def predict_cross_league(self, home_name, away_name, fixture_date, p_home, p_away):
        """Expected goals for teams from different leagues; p_home / p_away are
        outside win probabilities (fractions, de-vigged). Teams missing from the
        history are treated as average members of the other side's league."""
        day = fixture_date.toordinal()
        th, ta = self.find_team(home_name, day), self.find_team(away_name, day)
        if th is None and ta is None:
            return None
        gh, ga = (th[0] if th else ta[0]), (ta[0] if ta else th[0])
        mu_h_h, mu_a_h, g_h = self.fe.slow.league_means(gh)
        mu_h_a, mu_a_a, g_a = self.fe.slow.league_means(ga)
        mu_h, mu_a = (mu_h_h + mu_h_a) / 2, (mu_a_h + mu_a_a) / 2

        def rating(team, grp, g_val):
            if team is None:
                return 1.0, 1.0, 0.0
            return self.fe.slow.ratings(team[0], team[1], day, g_val)

        att_h, dfn_h, w_h = rating(th, gh, g_h)
        att_a, dfn_a, w_a = rating(ta, ga, g_a)
        lam_h0, lam_a0 = mu_h * att_h * dfn_a, mu_a * att_a * dfn_h
        lam_h, lam_a = fit_supremacy(lam_h0, lam_a0, p_home - p_away)
        return {
            "lam_home": lam_h, "lam_away": lam_a,
            "lam_home_before": lam_h0, "lam_away_before": lam_a0,
            "eff_home": round(w_h, 1), "eff_away": round(w_a, 1),
            "matched_home": f"{th[0]}:{th[1]}" if th else None,
            "matched_away": f"{ta[0]}:{ta[1]}" if ta else None,
            "missing": [n for n, t in ((home_name, th), (away_name, ta)) if t is None],
        }

    def analyze_cross(self, home_name, away_name, pred, probs=None) -> dict:
        """Poisson-total estimate calibrated like V3 (the V4 features are domestic)."""
        out = analyze_match_v3(home_name, away_name, pred["lam_home"], pred["lam_away"],
                               self.calibrators, (pred["eff_home"], pred["eff_away"]))
        out["model_version"] = "cross-league"
        out["data_quality"] = "CROSS_LOW" if pred["missing"] else "CROSS"
        out["data_quality_note"] = (
            "Teams from different leagues: relative strength comes from the supplied win "
            "probabilities, not from matches between these leagues. Rough estimate, "
            "not validated on Champions League games."
            + (f" No history for: {', '.join(pred['missing'])} (treated as league-average)."
               if pred["missing"] else ""))
        if probs is not None:               # win-or-draw straight from the supplied probabilities
            return attach_outcome_markets(out, probs, "supplied")
        return attach_outcome_markets(out, outcome_probs(pred["lam_home"], pred["lam_away"]), "poisson")

    def analyze(self, home_name, away_name, prediction) -> dict:
        """V4 model when available, otherwise the calibrated V3 Poisson model;
        plus result markets (home/draw/away, win-or-draw) and the ranked options."""
        eff = (prediction["eff_home"], prediction["eff_away"])
        if self.model is not None:
            out = analyze_match_v4(home_name, away_name, prediction["features"], self.model, eff)
        else:
            out = analyze_match_v3(home_name, away_name, prediction["lam_home"],
                                   prediction["lam_away"], self.calibrators, eff)
        if self.outcome_model is not None and "features" in prediction:
            probs, source = self.outcome_model.predict(prediction["features"]), "model"
        else:
            probs, source = outcome_probs(prediction["lam_home"], prediction["lam_away"]), "poisson"
        return attach_outcome_markets(out, probs, source)


_lock = threading.Lock()
_state = None


def get_state() -> RatingsState:
    """Build the ratings once; safe to call from several threads at the same time."""
    global _state
    with _lock:
        if _state is None:
            _state = RatingsState()
        return _state


def _clear_state() -> None:
    global _state
    with _lock:
        _state = None


get_state.cache_clear = _clear_state          # same API the old lru_cache offered
