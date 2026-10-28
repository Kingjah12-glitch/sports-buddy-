
from datetime import date

from fastapi import APIRouter, HTTPException, Query

from app.services.sports_api import (
    SportsAPIError,
    fetch_football_data,
)

router = APIRouter(
    prefix="/api/v1",
    tags=["Football Data"],
)


def format_fixture(item: dict) -> dict:
    fixture = item.get("fixture", {})
    teams = item.get("teams", {})
    goals = item.get("goals", {})
    league = item.get("league", {})

    return {
        "fixture_id": fixture.get("id"),
        "date": fixture.get("date"),
        "status": fixture.get("status", {}).get("short"),
        "elapsed_minutes": fixture.get("status", {}).get("elapsed"),
        "league": league.get("name"),
        "country": league.get("country"),
        "home_team": teams.get("home", {}).get("name"),
        "away_team": teams.get("away", {}).get("name"),
        "home_score": goals.get("home"),
        "away_score": goals.get("away"),
    }


@router.get("/live-scores")
async def get_live_scores():
    try:
        data = await fetch_football_data(
            "fixtures",
            {"live": "all"},
        )

        return {
            "count": len(data.get("response", [])),
            "matches": [
                format_fixture(item)
                for item in data.get("response", [])
            ],
        }

    except SportsAPIError as error:
        raise HTTPException(
            status_code=502,
            detail=str(error),
        ) from error


@router.get("/fixtures")
async def get_fixtures(
    match_date: date = Query(
        default_factory=date.today,
        alias="date",
    ),
):
    try:
        data = await fetch_football_data(
            "fixtures",
            {
                "date": match_date.isoformat(),
                "timezone": "Africa/Lagos",
            },
        )

        return {
            "date": match_date.isoformat(),
            "count": len(data.get("response", [])),
            "matches": [
                format_fixture(item)
                for item in data.get("response", [])
            ],
        }

    except SportsAPIError as error:
        raise HTTPException(
            status_code=502,
            detail=str(error),
        ) from error
