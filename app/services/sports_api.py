
import httpx

from app.config import (
    API_FOOTBALL_BASE_URL,
    API_FOOTBALL_KEY,
)


class SportsAPIError(Exception):
    pass


async def fetch_football_data(endpoint: str, params: dict | None = None):
    if not API_FOOTBALL_KEY:
        raise SportsAPIError(
            "API key is missing. Configure API_FOOTBALL_KEY in .env."
        )

    url = f"{API_FOOTBALL_BASE_URL.rstrip('/')}/{endpoint.lstrip('/')}"

    headers = {
        "x-apisports-key": API_FOOTBALL_KEY,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                url,
                headers=headers,
                params=params or {},
            )

        response.raise_for_status()
        data = response.json()

    except httpx.HTTPStatusError as error:
        raise SportsAPIError(
            f"Sports provider returned HTTP {error.response.status_code}."
        ) from error
    except httpx.RequestError as error:
        raise SportsAPIError(
            "Could not connect to the sports data provider."
        ) from error
    except ValueError as error:
        raise SportsAPIError(
            "The sports provider returned invalid JSON."
        ) from error

    if data.get("errors"):
        raise SportsAPIError(
            f"Sports provider rejected the request: {data['errors']}"
        )

    return data
