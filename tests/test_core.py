import math
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.calibration import apply_calibrator, fit_calibrator
from app.services.market_analyzer_v3 import analyze_match_v3
from app.services.names import normalize_name
from app.services.ratings import RatingEngine, poisson_over_probabilities

client = TestClient(app)


# ---------------------------------------------------------------- names
def test_normalize_handles_empty_and_prefix_only():
    assert normalize_name("") == ""
    assert normalize_name(None) == ""
    assert normalize_name("FC") == "fc"          # old code crashed here


def test_normalize_prefixes_aliases_and_accents():
    assert normalize_name("1. FSV Mainz 05") == "mainz"
    assert normalize_name("Bayern München") == "bayern munich"
    assert normalize_name("Manchester United") == "man united"
    assert normalize_name("AC Milan") == "milan"


# ---------------------------------------------------------------- poisson
def test_poisson_tail_matches_direct_sum():
    lam = 2.7
    p15, p25 = poisson_over_probabilities(lam)
    pmf = lambda k: math.exp(-lam) * lam ** k / math.factorial(k)
    assert p15 == pytest.approx(1 - pmf(0) - pmf(1))
    assert p25 == pytest.approx(1 - pmf(0) - pmf(1) - pmf(2))


# ---------------------------------------------------------------- ratings
def test_no_prediction_without_history_and_no_lookahead():
    eng = RatingEngine(min_eff=3)
    assert eng.predict("L", "a", "b", 1000) is None
    for d in range(10):
        eng.update("L", "a", "b", 1000 + d, 2, 1)
    before = eng.predict("L", "a", "b", 1011)
    assert before is not None
    # predicting must not change state
    assert eng.predict("L", "a", "b", 1011) == before


def test_shrinkage_keeps_small_samples_near_league_average():
    eng = RatingEngine(k=16, min_eff=0.5)
    eng.update("L", "a", "b", 1000, 6, 0)        # one freak result
    lam_h, lam_a, *_ = eng.predict("L", "a", "b", 1001)
    assert lam_h < 2.3                            # not blown up to ~6


# ---------------------------------------------------------------- calibration
def test_calibrator_is_monotone_and_clamped():
    import random
    random.seed(1)
    probs = [random.random() for _ in range(5000)]
    ys = [1 if random.random() < p * 0.8 else 0 for p in probs]
    cal = fit_calibrator(probs, ys)
    assert cal["y"] == sorted(cal["y"])
    assert 0.01 <= apply_calibrator(cal, 0.0) <= apply_calibrator(cal, 1.0) <= 0.99
    assert apply_calibrator(None, 0.42) == 0.42


def test_v3_output_shape():
    out = analyze_match_v3("A", "B", 1.6, 1.2)
    assert out["model_version"] == "v3"
    m = out["markets"]["over_2_5_goals"]
    assert 0 < m["estimated_probability"] < 100
    assert m["fair_odds"] == pytest.approx(100 / m["estimated_probability"], rel=0.01)


# ---------------------------------------------------------------- API
def test_value_check_accepts_percent_and_fraction():
    a = client.post("/api/v1/predictions/value-check",
                    json={"market": "o2.5", "estimated_probability": 0.62, "decimal_odds": 1.9}).json()
    b = client.post("/api/v1/predictions/value-check",
                    json={"market": "o2.5", "estimated_probability": 62, "decimal_odds": 1.9}).json()
    assert a["estimated_probability_percent"] == b["estimated_probability_percent"] == 62.0
    assert a["assessment"] == b["assessment"] == "POTENTIAL VALUE"


def test_fixture_endpoint_with_mocked_provider(monkeypatch):
    import app.routers.predictions as preds

    async def fake_fetch(endpoint, params=None):
        return {"response": [{
            "fixture": {"id": 1, "date": "2026-10-24T14:00:00+00:00"},
            "league": {"name": "Premier League", "country": "England"},
            "teams": {"home": {"id": 1, "name": "Arsenal"},
                      "away": {"id": 2, "name": "Manchester United"}},
        }]}

    monkeypatch.setattr(preds, "fetch_football_data", fake_fetch)
    r = client.get("/api/v1/predictions/fixture/1")
    assert r.status_code == 200
    body = r.json()
    assert body["analysis"]["status"] == "analysis_complete"
    assert body["matched_as"]["away"] == "man united"
    assert body["analysis"]["markets"]["over_2_5_goals"]["calibrated"] is True


def test_fixture_endpoint_unknown_teams_gives_no_bet(monkeypatch):
    import app.routers.predictions as preds

    async def fake_fetch(endpoint, params=None):
        return {"response": [{
            "fixture": {"id": 2, "date": "2026-10-24T14:00:00+00:00"},
            "league": {"name": "Premier League", "country": "England"},
            "teams": {"home": {"id": 1, "name": "Zzyzx Rovers"},
                      "away": {"id": 2, "name": "Qwerty Town"}},
        }]}

    monkeypatch.setattr(preds, "fetch_football_data", fake_fetch)
    body = client.get("/api/v1/predictions/fixture/2").json()
    assert body["analysis"]["status"] == "insufficient_data"
    assert body["analysis"]["recommendation"] == "NO BET"


# ---------------------------------------------------------------- name resolving
def test_resolve_key_provider_spellings():
    from app.services.names import resolve_key
    cands = {"betis", "sevilla", "sociedad", "espanol", "barcelona", "inter",
             "milan", "paris sg", "paris", "lens", "hoffenheim"}
    n = normalize_name
    assert resolve_key(n("Real Betis Seville"), cands) == "betis"      # not sevilla
    assert resolve_key(n("Real Sociedad San Sebastian"), cands) == "sociedad"
    assert resolve_key(n("Espanyol Barcelona"), cands) == "espanol"    # not barcelona
    assert resolve_key(n("Inter Milano"), cands) == "inter"            # not milan
    assert resolve_key(n("Racing Club De Lens"), cands) == "lens"
    assert resolve_key(n("TSG Hoffenheim"), cands) == "hoffenheim"
    assert resolve_key(n("Paris FC"), cands) == "paris"                # not paris sg
    assert resolve_key(n("Totally Unknown United"), cands) is None


# ---------------------------------------------------------------- today.py
def _api_item(status, home, away, hg=None, ag=None, league="Premier League", country="England"):
    return {"fixture": {"id": 1, "date": "2026-10-18T13:00:00+00:00", "status": {"short": status}},
            "league": {"name": league, "country": country},
            "teams": {"home": {"name": home}, "away": {"name": away}},
            "goals": {"home": hg, "away": ag}}


def test_today_parses_api_items_and_predicts():
    from zoneinfo import ZoneInfo
    import today
    from app.services.ratings_store import get_state
    items = [_api_item("NS", "AFC Bournemouth", "Sunderland AFC"),
             _api_item("FT", "Arsenal FC", "Chelsea FC", 1, 0),            # finished -> not a fixture
             _api_item("NS", "Egypt A", "Egypt B", league="Premier League", country="Egypt")]
    fixtures = today.fixtures_from_api_items(items, ZoneInfo("Africa/Lagos"))
    assert len(fixtures) == 2 and fixtures[0]["kickoff"].strftime("%H:%M") == "14:00"   # UTC+1
    state = get_state()
    covered = [f for f in fixtures if state.covered_groups(f["country"], f["league"])]
    assert [f["home"] for f in covered] == ["AFC Bournemouth"]       # Egypt not mistaken for England
    rows, unmatched = today.predict_rows(covered, state)
    assert len(rows) == 1 and not unmatched
    assert 0 < rows[0]["p_over_2_5"] < rows[0]["p_over_1_5"] < 100


def test_today_results_refresh_is_idempotent(tmp_path):
    import today
    from app.services.ratings_store import get_state
    state = get_state()
    new = today.results_from_api_items(
        [_api_item("FT", "Arsenal FC", "Chelsea FC", 2, 1), _api_item("NS", "Leeds United", "Everton FC")],
        state)
    assert len(new) == 1 and new[0]["Competition"] == "England_Premier_League"
    path = tmp_path / "recent.csv"
    assert today.merge_recent_results(new, path) == 1
    assert today.merge_recent_results(new, path) == 0                # no duplicates on re-run


def test_odds_edge_columns():
    from datetime import datetime, timezone
    import today
    from app.services.ratings_store import get_state
    fx = [{"kickoff": datetime(2026, 10, 18, 13, tzinfo=timezone.utc), "country": "England",
           "league": "Premier League", "home": "Brighton & Hove Albion", "away": "Crystal Palace"}]
    odds = {(today.normalize_name("Brighton & Hove Albion"), today.normalize_name("Crystal Palace")):
            {"over_1_5": 1.40, "over_2_5": 2.00}}
    rows, _ = today.predict_rows(fx, get_state(), odds)
    assert rows[0]["edge_o25_pp"] == pytest.approx(rows[0]["p_over_2_5"] - 50.0, abs=0.1)


def test_refresh_survives_plan_limited_dates(monkeypatch, capsys, tmp_path):
    """Free API plans reject dates older than yesterday: skip them, don't crash."""
    import asyncio
    from argparse import Namespace
    from datetime import date
    import today
    from app.services.sports_api import SportsAPIError

    async def fake_day(day):
        if day < date(2026, 10, 17):
            raise SportsAPIError("Free plans do not have access to this date")
        return [_api_item("FT", "Arsenal FC", "Chelsea FC", 2, 1)]

    saved = {}
    monkeypatch.setattr(today, "_fetch_day", fake_day)
    monkeypatch.setattr(today, "OUT_DIR", tmp_path)          # never write into the real data/today
    monkeypatch.setattr(today, "merge_recent_results", lambda rows: saved.setdefault("n", len(rows)))
    args = Namespace(date="2026-10-19", tz="Africa/Lagos", refresh_results=True, refresh_days=3,
                     fixtures_file="data/today/fixtures_2026-10-18.csv", odds=None)
    asyncio.run(today.main_async(args))
    out = capsys.readouterr().out
    assert "Skipped results for 2026-10-16" in out and saved["n"] == 2   # two allowed days, one skipped


# ---------------------------------------------------------------- V4
def test_v4_model_loaded_and_probabilities_sane():
    from datetime import date
    from app.services.ratings_store import get_state
    state = get_state()
    assert state.model is not None
    pred = state.predict_fixture("Arsenal FC", "Chelsea FC", date(2026, 10, 24), "England", "Premier League")
    out = state.analyze("Arsenal FC", "Chelsea FC", pred)
    m = out["markets"]
    assert out["model_version"] == "v4"
    assert 0 < m["over_2_5_goals"]["estimated_probability"] < m["over_1_5_goals"]["estimated_probability"] < 100


def test_analyze_falls_back_to_v3_without_model():
    from datetime import date
    from app.services.ratings_store import get_state
    state = get_state()
    pred = state.predict_fixture("Arsenal FC", "Chelsea FC", date(2026, 10, 24), "England", "Premier League")
    saved, state.model = state.model, None
    try:
        assert state.analyze("A", "C", pred)["model_version"] == "v3"
    finally:
        state.model = saved


# ---------------------------------------------------------------- /day endpoint
def test_day_endpoint_groups_by_league_from_file(monkeypatch, tmp_path):
    import app.routers.predictions as preds
    (tmp_path / "fixtures_2026-10-18.csv").write_text(
        "Date,Time,Country,League,Home,Away\n"
        "2026-10-18,13:00,England,Premier League,AFC Bournemouth,Sunderland AFC\n"
        "2026-10-18,13:00,England,Premier League,Leeds United,Manchester United\n"
        "2026-10-18,19:00,Spain,La Liga,Real Madrid,Sevilla FC\n"
        "2026-10-18,19:00,Egypt,Premier League,Foo,Bar\n"
        "2026-10-18,20:00,England,Premier League,Zzyzx Rovers,Qwerty Town\n", encoding="utf-8")
    monkeypatch.setattr(preds, "TODAY_DIR", tmp_path)
    r = client.get("/api/v1/predictions/day?date=2026-10-18&source=file")
    assert r.status_code == 200
    body = r.json()
    assert [lg["league"] for lg in body["leagues"]] == ["Premier League", "La Liga"]   # fixed order
    assert [len(lg["matches"]) for lg in body["leagues"]] == [2, 1]
    assert body["summary"]["predicted"] == 3 and body["summary"]["team_names_not_matched"] == 1
    assert body["not_covered"][0]["competition"].startswith("Egypt")
    m = body["leagues"][0]["matches"][0]
    assert m["kickoff"] == "14:00" and 0 < m["over_2_5"]["probability"] < m["over_1_5"]["probability"] < 100


def test_day_endpoint_auto_falls_back_to_file(monkeypatch, tmp_path):
    import app.routers.predictions as preds
    from app.services.sports_api import SportsAPIError

    async def refuse(endpoint, params=None):
        raise SportsAPIError("Free plans do not have access to this date")

    (tmp_path / "fixtures_2026-10-18.csv").write_text(
        "Date,Time,Country,League,Home,Away\n2026-10-18,19:00,Spain,La Liga,Real Madrid,Sevilla FC\n",
        encoding="utf-8")
    monkeypatch.setattr(preds, "fetch_football_data", refuse)
    monkeypatch.setattr(preds, "TODAY_DIR", tmp_path)
    body = client.get("/api/v1/predictions/day?date=2026-10-18").json()
    assert body["source"].startswith("file:") and "Free plans" in body["fallback_reason"]
    assert client.get("/api/v1/predictions/day?date=2026-10-18&source=api").status_code == 502
    assert client.get("/api/v1/predictions/day?date=2031-01-01").status_code == 404


# ---------------------------------------------------------------- cross-league (Champions League)
def test_supremacy_fit_hits_target_and_devig():
    from app.services.cross_league import (devig_odds, devig_percentages, fit_supremacy,
                                           win_minus_loss)
    lh, la = fit_supremacy(1.5, 1.2, 0.45)
    assert win_minus_loss(lh, la) == pytest.approx(0.45, abs=1e-3)
    assert lh > la
    assert sum(devig_percentages(59.7, 21.4, 18.9)) == pytest.approx(1.0)
    assert sum(devig_odds(1.6, 4.0, 5.5)) == pytest.approx(1.0)


def test_cross_league_prediction_for_teams_from_different_leagues():
    from datetime import date
    from app.services.cross_league import devig_percentages
    from app.services.ratings_store import get_state
    state = get_state()
    ph, _, pa = devig_percentages(62.9, 20.1, 17.0)
    pred = state.predict_cross_league("Liverpool FC", "Villarreal CF", date(2026, 10, 20), ph, pa)
    assert pred["missing"] == [] and pred["lam_home"] > pred["lam_away"]
    out = state.analyze_cross("Liverpool FC", "Villarreal CF", pred)
    assert out["data_quality"] == "CROSS"
    assert 0 < out["markets"]["over_2_5_goals"]["estimated_probability"] < out["markets"]["over_1_5_goals"]["estimated_probability"] < 100
    # club outside the history -> flagged, still answered from the other side's league
    pred2 = state.predict_cross_league("Sabah Masazir", "Borussia Dortmund", date(2026, 10, 20), 0.12, 0.76)
    assert pred2["missing"] == ["Sabah Masazir"]
    assert state.analyze_cross("Sabah Masazir", "Borussia Dortmund", pred2)["data_quality"] == "CROSS_LOW"


def test_day_endpoint_adds_champions_league_tab_first(monkeypatch, tmp_path):
    import app.routers.predictions as preds
    (tmp_path / "fixtures_2026-10-20.csv").write_text(
        "Date,Time,Country,League,Home,Away,PH,PD,PA\n"
        "2026-10-20,19:00,World,Champions League,Liverpool FC,Villarreal CF,62.9,20.1,17.0\n", encoding="utf-8")

    async def live(endpoint, params=None):        # live API knows only a domestic match
        return {"response": [{"fixture": {"id": 9, "date": "2026-10-20T18:00:00+00:00", "status": {"short": "NS"}},
                              "league": {"name": "La Liga", "country": "Spain"},
                              "teams": {"home": {"name": "Real Madrid"}, "away": {"name": "Sevilla FC"}}}]}

    monkeypatch.setattr(preds, "fetch_football_data", live)
    monkeypatch.setattr(preds, "TODAY_DIR", tmp_path)
    body = client.get("/api/v1/predictions/day?date=2026-10-20").json()
    assert body["source"] == "api-football+file"
    assert [lg["league"] for lg in body["leagues"]] == ["Champions League", "La Liga"]
    assert body["leagues"][0]["matches"][0]["data_quality"] == "CROSS"


def test_newly_promoted_team_is_predicted_but_flagged_low():
    from datetime import date
    from app.services.ratings_store import get_state
    state = get_state()
    pred = state.predict_fixture("Tottenham Hotspur", "Coventry City", date(2026, 10, 19), "England", "Premier League")
    assert pred is not None                                  # used to be refused (< 6 matches of history)
    out = state.analyze("Tottenham Hotspur", "Coventry City", pred)
    assert out["data_quality"] == "LOW"
    assert 0 < out["markets"]["over_2_5_goals"]["estimated_probability"] < out["markets"]["over_1_5_goals"]["estimated_probability"] < 100


# ---------------------------------------------------------------- win-or-draw + pick
def test_outcome_markets_and_pick_for_domestic_match():
    from datetime import date
    from app.services.ratings_store import get_state
    state = get_state()
    pred = state.predict_fixture("Arsenal FC", "Everton FC", date(2026, 10, 24), "England", "Premier League")
    out = state.analyze("Arsenal FC", "Everton FC", pred)
    o = out["outcomes"]
    assert o["home"] + o["draw"] + o["away"] == pytest.approx(100, abs=0.3)
    m = out["markets"]
    assert m["home_or_draw"]["estimated_probability"] == pytest.approx(o["home"] + o["draw"], abs=0.3)
    assert m["away_or_draw"]["estimated_probability"] == pytest.approx(o["away"] + o["draw"], abs=0.3)
    assert m["under_2_5_goals"]["estimated_probability"] == pytest.approx(100 - m["over_2_5_goals"]["estimated_probability"], abs=0.1)
    probs = [x["probability"] for x in out["options"]]
    assert probs == sorted(probs, reverse=True) and out["pick"]["probability"] == probs[0]
    assert out["pick"]["basis"] == "most_likely" and "not best value" in out["pick"]["note"]


def test_cross_league_win_or_draw_uses_supplied_probabilities():
    from datetime import date
    from app.services.cross_league import devig_percentages
    from app.services.ratings_store import get_state
    state = get_state()
    probs = devig_percentages(62.9, 20.1, 17.0)
    pred = state.predict_cross_league("Liverpool FC", "Villarreal CF", date(2026, 10, 20), probs[0], probs[2])
    out = state.analyze_cross("Liverpool FC", "Villarreal CF", pred, probs)
    assert out["outcomes"]["source"] == "supplied"
    assert out["markets"]["home_or_draw"]["estimated_probability"] == pytest.approx(83.0, abs=0.2)


def test_day_endpoint_returns_options_and_pick(monkeypatch, tmp_path):
    import app.routers.predictions as preds
    (tmp_path / "fixtures_2026-10-24.csv").write_text(
        "Date,Time,Country,League,Home,Away\n2026-10-24,14:00,England,Premier League,Arsenal FC,Everton FC\n", encoding="utf-8")
    monkeypatch.setattr(preds, "TODAY_DIR", tmp_path)
    m = client.get("/api/v1/predictions/day?date=2026-10-24&source=file").json()["leagues"][0]["matches"][0]
    assert {o["key"] for o in m["options"]} == {"over_1_5_goals", "over_2_5_goals", "under_2_5_goals", "home_or_draw", "away_or_draw"}
    assert m["pick"]["probability"] == max(o["probability"] for o in m["options"])
    assert set(m["outcomes"]) >= {"home", "draw", "away"}


def test_league_name_recognition_beyond_top_five():
    from app.services.ratings_store import get_state
    s = get_state()
    expect = {("Germany", "Bundesliga"): "Germany_Bundesliga", ("Germany", "2. Bundesliga"): "Germany_Bundesliga_2",
              ("Romania", "Liga I"): "Romania_Superliga", ("Netherlands", "Eredivisie"): "Netherlands_Eredivisie",
              ("Belgium", "Jupiler Pro League"): "Belgium_Pro_League", ("England", "Championship"): "England_Championship",
              ("Scotland", "Premiership"): "Scotland_Premiership", ("Turkey", "Super Lig"): "Turkey_Super_Lig",
              ("Brazil", "Serie A"): "Brazil_Serie_A", ("Japan", "J1 League"): "Japan_J1_League",
              ("Spain", "Segunda División"): "Spain_Segunda", ("USA", "Major League Soccer"): "USA_MLS"}
    for (country, league), group in expect.items():
        assert s.covered_groups(country, league) == [group], (country, league, s.covered_groups(country, league))
    assert s.covered_groups("Egypt", "Premier League") == []


# ---------------------------------------------------------------- score_day
def test_score_day_matches_predictions_to_results(tmp_path):
    from datetime import date
    import score_day
    preds = [{"league": "Premier League", "home": "Arsenal FC", "away": "Everton FC", "xg_total": "2.6",
              "p_over_1_5": "78", "p_over_2_5": "55", "p_1x": "87", "p_x2": "33", "pick": "Home win or draw",
              "pick_probability": "87", "model_version": "v4"},
             {"league": "Premier League", "home": "Chelsea FC", "away": "Tottenham Hotspur", "xg_total": "3.2",
              "p_over_1_5": "83", "p_over_2_5": "62", "p_1x": "77", "p_x2": "46", "pick": "Over 1.5 goals",
              "pick_probability": "83", "model_version": "v4"},
             {"league": "Premier League", "home": "Unplayed United", "away": "Nobody FC", "xg_total": "2.5",
              "p_over_1_5": "75", "p_over_2_5": "50", "p_1x": "60", "p_x2": "60", "pick": "Over 1.5 goals",
              "pick_probability": "75", "model_version": "v4"}]
    results = [{"Date": "2026-10-24", "Competition": "England_Premier_League", "Home": "Arsenal", "Away": "Everton",
                "HG": "2", "AG": "0"},
               {"Date": "2026-10-24", "Competition": "England_Premier_League", "Home": "Chelsea", "Away": "Tottenham",
                "HG": "0", "AG": "2"}]
    scored, missing = score_day.score_rows(preds, results, date(2026, 10, 24))
    assert len(scored) == 2 and len(missing) == 1
    a, c = scored
    assert (a["score"], a["result"], a["o15"], a["o25"], a["r1x"], a["rx2"], a["pick_hit"]) == ("2-0", "H", 1, 0, 1, 0, 1)
    assert (c["score"], c["result"], c["o15"], c["r1x"], c["rx2"], c["pick_hit"]) == ("0-2", "A", 1, 0, 1, 1)
    assert "Over 1.5" in "\n".join(score_day.summarise(scored, "t"))


# ---------------------------------------------------------------- build_site (static website)
def test_build_site_writes_static_json_index_and_config(monkeypatch, tmp_path):
    import json
    import argparse
    import asyncio
    import build_site
    from app.services.sports_api import SportsAPIError

    today_dir = tmp_path / "today"
    today_dir.mkdir()
    (today_dir / "fixtures_2026-10-24.csv").write_text(
        "Date,Time,Country,League,Home,Away\n2026-10-24,14:00,England,Premier League,Arsenal FC,Everton FC\n"
        "2026-10-24,19:00,Spain,La Liga,Real Madrid,Sevilla FC\n", encoding="utf-8")

    async def no_api(endpoint, params=None):
        raise SportsAPIError("API key is missing")

    monkeypatch.setattr(build_site, "fetch_football_data", no_api)
    monkeypatch.setattr(build_site, "SITE_DIR", tmp_path / "docs")
    monkeypatch.setattr(build_site, "TODAY_DIR", today_dir)
    args = argparse.Namespace(dates=None, today="2026-10-24", tz="Africa/Lagos", no_refresh=True, refresh_days=1)
    assert asyncio.run(build_site.main_async(args)) == 0

    docs = tmp_path / "docs"
    day = json.loads((docs / "data" / "2026-10-24.json").read_text(encoding="utf-8"))
    assert [lg["league"] for lg in day["leagues"]] == ["Premier League", "La Liga"]
    assert day["leagues"][0]["matches"][0]["kickoff_iso"].startswith("2026-10-24T15:00")     # WAT = UTC+1
    index = json.loads((docs / "data" / "index.json").read_text())
    assert index["dates"] == ["2026-10-24"] and index["today"] == "2026-10-24"
    assert 'apiBase: ""' in (docs / "config.js").read_text()                                  # static mode
    assert (docs / "index.html").exists() and (docs / "script.js").exists() and (docs / ".nojekyll").exists()
    assert (today_dir / "predictions_2026-10-24.csv").exists()                                # frozen for scoring
    # tomorrow has no fixtures file and no API: skipped, not fatal
    assert not (docs / "data" / "2026-10-25.json").exists()


# ---------------------------------------------------------------- live hosting: CORS, cache, refresh
def test_cors_allows_the_github_pages_site_and_blocks_strangers():
    ok = client.get("/health", headers={"Origin": "https://kingjah12-glitch.github.io"})
    assert ok.headers.get("access-control-allow-origin") == "https://kingjah12-glitch.github.io"
    other = client.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in other.headers


def test_allowed_origins_env_extension(monkeypatch):
    from app.main import allowed_origins
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://mysite.io/, https://other.io")
    assert "https://mysite.io" in allowed_origins() and "https://other.io" in allowed_origins()
    monkeypatch.setenv("ALLOWED_ORIGINS", "*")
    assert allowed_origins() == ["*"]


def test_day_endpoint_is_cached_so_visitors_cannot_burn_the_api_quota(monkeypatch, tmp_path):
    import app.routers.predictions as preds
    calls = {"n": 0}

    async def live(endpoint, params=None):
        calls["n"] += 1
        return {"response": [{"fixture": {"id": 9, "date": "2026-11-02T18:00:00+00:00", "status": {"short": "NS"}},
                              "league": {"name": "La Liga", "country": "Spain"},
                              "teams": {"home": {"name": "Real Madrid"}, "away": {"name": "Sevilla FC"}}}]}

    preds._day_cache.clear()
    monkeypatch.setattr(preds, "fetch_football_data", live)
    monkeypatch.setattr(preds, "TODAY_DIR", tmp_path)
    for _ in range(5):
        assert client.get("/api/v1/predictions/day?date=2026-11-02").status_code == 200
    assert calls["n"] == 1                       # five page loads, one API-Football call
    client.get("/api/v1/predictions/day?date=2026-11-03")
    assert calls["n"] == 2                       # a different day is a new call
    preds._day_cache.clear()


def test_refresh_results_adds_finished_matches(monkeypatch, tmp_path):
    import asyncio
    from datetime import date
    import app.services.daily as daily
    from app.services.ratings_store import get_state

    async def fake(endpoint, params=None):
        return {"response": [_api_item("FT", "Arsenal FC", "Chelsea FC", 2, 1)]}

    saved = {}
    monkeypatch.setattr(daily, "merge_recent_results", lambda rows: saved.setdefault("n", len(rows)))
    assert asyncio.run(daily.refresh_results(date(2026, 10, 26), get_state(), fake, 1)) == 1
    assert saved["n"] == 1


def test_build_site_never_overwrites_an_edited_config(monkeypatch, tmp_path):
    import build_site
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "config.js").write_text('window.SB_CONFIG = { apiBase: "https://my-api.onrender.com", dataBase: "data" };')
    monkeypatch.setattr(build_site, "SITE_DIR", docs)
    build_site.sync_site()
    assert "my-api.onrender.com" in (docs / "config.js").read_text()
    assert (docs / "index.html").exists()
