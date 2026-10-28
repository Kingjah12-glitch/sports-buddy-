from datetime import date

from fastapi import APIRouter, HTTPException, Query

from app.services.sports_api import (
    SportsAPIError,
    fetch_football_data,
)

router = APIRouter(
    prefix="/api/v1/matches",
    tags=["Matches"],
)


@router.get("/upcoming")
async def upcoming_matches(
    match_date: date = Query(default=None, alias="date"),
):
    if match_date is None:
        match_date = date.today()

    try:
        data = await fetch_football_data(
            "fixtures",
            {
                "date": match_date.isoformat(),
                "timezone": "Africa/Lagos",
            },
        )

        fixtures = []

        for item in data.get("response", []):
            fixture = item.get("fixture", {})
            status = fixture.get("status", {}).get("short")

            # Only include matches that have not started.
            if status not in ("NS", "TBD"):
                continue

            teams = item.get("teams", {})
            league = item.get("league", {})

            fixtures.append(
                {
                    "fixture_id": fixture.get("id"),
                    "kickoff": fixture.get("date"),
                    "status": status,
                    "league": league.get("name"),
                    "home_team": teams.get("home", {}).get("name"),
                    "away_team": teams.get("away", {}).get("name"),
                }
            )

        return {
            "date": match_date.isoformat(),
            "count": len(fixtures),
            "matches": fixtures,
        }

    except SportsAPIError as error:
        raise HTTPException(
            status_code=502,
            detail=str(error),
        ) from error

@router.get("/{fixture_id}")
async def get_match_details(fixture_id: int):
    try:
        data = await fetch_football_data(
            "fixtures",
            {
                "id": fixture_id,
                "timezone": "Africa/Lagos",
            },
        )

        matches = data.get("response", [])

        if not matches:
            raise HTTPException(
                status_code=404,
                detail="Match not found. Check the fixture ID.",
            )

        item = matches[0]
        fixture = item.get("fixture", {})
        teams = item.get("teams", {})
        league = item.get("league", {})
        goals = item.get("goals", {})
        status = fixture.get("status", {})

        return {
            "fixture_id": fixture.get("id"),
            "kickoff": fixture.get("date"),
            "status": status.get("long"),
            "status_short": status.get("short"),
            "elapsed_minutes": status.get("elapsed"),
            "league": league.get("name"),
            "country": league.get("country"),
            "home_team": teams.get("home", {}).get("name"),
            "away_team": teams.get("away", {}).get("name"),
            "home_score": goals.get("home"),
            "away_score": goals.get("away"),
        }

    except SportsAPIError as error:
        raise HTTPException(
            status_code=502,
            detail=str(error),
        ) from error
    
@router.get("/team/{team_id}/recent")
async def get_recent_team_results(team_id: int, last: int = 5):
    if last < 1 or last > 10:
        raise HTTPException(
            status_code=400,
            detail="The number of matches must be between 1 and 10.",
        )

    try:
        data = await fetch_football_data(
            "fixtures",
            {
                "team": team_id,
                "last": last,
                "timezone": "Africa/Lagos",
            },
        )

        results = []

        for item in data.get("response", []):
            fixture = item.get("fixture", {})
            teams = item.get("teams", {})
            goals = item.get("goals", {})

            home = teams.get("home", {})
            away = teams.get("away", {})

            # Skip matches that do not have a final score.
            if goals.get("home") is None or goals.get("away") is None:
                continue

            is_home = home.get("id") == team_id

            results.append(
                {
                    "fixture_id": fixture.get("id"),
                    "date": fixture.get("date"),
                    "opponent": (
                        away.get("name") if is_home
                        else home.get("name")
                    ),
                    "venue": "home" if is_home else "away",
                    "goals_scored": (
                        goals.get("home") if is_home
                        else goals.get("away")
                    ),
                    "goals_conceded": (
                        goals.get("away") if is_home
                        else goals.get("home")
                    ),
                    "result": (
                        "DRAW"
                        if goals.get("home") == goals.get("away")
                        else (
                            "WIN"
                            if (
                                goals.get("home") > goals.get("away")
                            ) == is_home
                            else "LOSS"
                        )
                    ),
                }
            )

        return {
            "team_id": team_id,
            "requested_matches": last,
            "count": len(results),
            "results": results,
        }

    except SportsAPIError as error:
        raise HTTPException(
            status_code=502,
            detail=str(error),
        ) from error  