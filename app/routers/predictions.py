import time
from datetime import date as date_type
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app.services.daily import get_tz
from app.services.day_payload import DayUnavailable, build_day_payload
from app.services.history_loader import PROJECT_ROOT
from app.services.market_analyzer import analyze_match
from app.services.ratings_store import get_state
from app.services.sports_api import SportsAPIError, fetch_football_data

router = APIRouter(
    prefix="/api/v1/predictions",
    tags=["Predictions"],
)

TODAY_DIR = PROJECT_ROOT / "data" / "today"     # optional offline fixtures files
CACHE_SECONDS = 600                              # one API-Football call per day/zone per 10 minutes
_day_cache: dict = {}


# --------------------------------------------------------------------- schemas
class ValueCheckRequest(BaseModel):
    market: str = Field(min_length=1, max_length=100)
    # Accepts a fraction (0.62) or a percentage (62). Values above 1 are
    # treated as percentages, so the /analyze output can be pasted in directly.
    estimated_probability: float = Field(gt=0, le=100)
    decimal_odds: float = Field(gt=1, le=1000)


class TeamForm(BaseModel):
    team: str = Field(min_length=1, max_length=80)
    goals_scored: list[int] = Field(min_length=5, max_length=10)
    goals_conceded: list[int] = Field(min_length=5, max_length=10)


class MatchAnalysisRequest(BaseModel):
    home: TeamForm
    away: TeamForm


# ------------------------------------------------------------------- endpoints
@router.post("/analyze")
def predict_match(request: MatchAnalysisRequest):
    """Legacy V1 model on goals supplied by the caller (kept for manual use)."""
    try:
        return analyze_match(
            home_team=request.home.team,
            away_team=request.away.team,
            home_scored=request.home.goals_scored,
            home_conceded=request.home.goals_conceded,
            away_scored=request.away.goals_scored,
            away_conceded=request.away.goals_conceded,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/fixture/{fixture_id}")
async def analyze_fixture(fixture_id: int):
    """V3 analysis of an API-Football fixture using the local CSV history."""
    try:
        fixture_data = await fetch_football_data("fixtures", {"id": fixture_id})
    except SportsAPIError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    fixtures = fixture_data.get("response", [])
    if not fixtures:
        raise HTTPException(
            status_code=404, detail="Fixture not found. Check the fixture ID."
        )

    item = fixtures[0]
    teams = item.get("teams", {})
    home_name = teams.get("home", {}).get("name")
    away_name = teams.get("away", {}).get("name")
    league = item.get("league", {})

    if not home_name or not away_name:
        raise HTTPException(status_code=502, detail="Could not identify both teams.")

    try:
        fixture_date = datetime.fromisoformat(
            str(item.get("fixture", {}).get("date", "")).replace("Z", "+00:00")
        ).date()
    except ValueError as error:
        raise HTTPException(
            status_code=502, detail="Could not determine the fixture date."
        ) from error

    try:
        state = await run_in_threadpool(get_state)   # first call builds ratings
    except FileNotFoundError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    prediction = await run_in_threadpool(
        state.predict_fixture,
        home_name, away_name, fixture_date,
        league.get("country"), league.get("name"),
    )

    base = {
        "fixture_id": fixture_id,
        "home_team": home_name,
        "away_team": away_name,
        "league": league.get("name"),
        "history_source": "local_csv",
        "data_through": str(state.last_date),
    }

    if prediction is None:
        return {
            **base,
            "analysis": {
                "status": "insufficient_data",
                "recommendation": "NO BET",
                "message": (
                    "Could not match both teams to the local CSV history with "
                    "enough past matches. The competition may not be covered, or "
                    "the team names may need an alias in app/services/names.py."
                ),
            },
            "notice": "No estimate was generated.",
        }

    analysis = state.analyze(home_name, away_name, prediction)
    return {
        **base,
        "matched_as": {
            "competition_file": prediction["competition_file_group"],
            "home": prediction["matched_home"],
            "away": prediction["matched_away"],
        },
        "analysis": analysis,
        "notice": (
            "Estimates are calibrated on historical results. Backtests show "
            "bookmaker prices are at least as accurate, so a high probability "
            "is not by itself a reason to bet."
        ),
    }


@router.get("/day")
async def predictions_for_day(
    match_date: date_type = Query(default=None, alias="date"),
    tz: str = "Africa/Lagos",
    source: str = Query(default="auto", pattern="^(auto|api|file)$"),
):
    """Predictions for every covered match on a day, grouped by league.

    source=auto tries API-Football first and falls back to
    data/today/fixtures_<date>.csv; 'api' / 'file' force one of them.
    """
    try:
        zone = get_tz(tz)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    day = match_date or datetime.now(zone).date()
    cache_key = (day.isoformat(), tz, source)
    hit = _day_cache.get(cache_key)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    try:
        state = await run_in_threadpool(get_state)
    except FileNotFoundError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    try:
        payload, _ = await build_day_payload(day, zone, tz, source, state, fetch_football_data, TODAY_DIR)
    except DayUnavailable as error:
        raise HTTPException(status_code=error.status, detail=error.detail) from error
    _day_cache[cache_key] = (time.monotonic(), payload)       # only successful answers are cached
    return payload


@router.post("/value-check")
async def check_betting_value(request: ValueCheckRequest):
    probability = request.estimated_probability
    if probability > 1:
        probability /= 100.0
    odds = request.decimal_odds

    implied_probability = 1 / odds
    expected_return = (probability * odds) - 1
    fair_odds = 1 / probability
    probability_edge = probability - implied_probability

    # Require a minimum estimated edge of 5 percentage points.
    if probability_edge >= 0.05 and expected_return > 0:
        assessment = "POTENTIAL VALUE"
        message = (
            "The supplied probability exceeds the odds-implied probability by "
            "at least five percentage points. In backtests, model 'edges' of "
            "this kind did NOT turn into profit, so verify before relying on it."
        )
    else:
        assessment = "NO BET"
        message = (
            "The estimated edge is below the required threshold. "
            "Do not force a betting recommendation."
        )

    return {
        "market": request.market,
        "estimated_probability_percent": round(probability * 100, 2),
        "decimal_odds": odds,
        "odds_implied_probability_percent": round(implied_probability * 100, 2),
        "fair_odds_estimate": round(fair_odds, 2),
        "probability_edge_percentage_points": round(probability_edge * 100, 2),
        "estimated_expected_return_percent": round(expected_return * 100, 2),
        "assessment": assessment,
        "message": message,
        "notice": (
            "Illustrative estimates only. Model uncertainty, bookmaker margin, "
            "and real-world performance are not fully accounted for."
        ),
    }
