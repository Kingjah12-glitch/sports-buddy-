import asyncio
import logging
import os
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware

from app.routers import predictions
from app.routers import live_scores
from app.routers import matches
from app.services.daily import get_tz, refresh_results
from app.services.ratings_store import get_state
from app.services.sports_api import fetch_football_data

log = logging.getLogger("sports_buddy")


REFRESH_EVERY_SECONDS = 6 * 3600


async def refresh_loop():
    """Every few hours: pull yesterday's finished matches and rebuild the ratings."""
    await asyncio.sleep(5)
    while True:
        try:
            state = await run_in_threadpool(get_state)
            today = datetime.now(get_tz("Africa/Lagos")).date()
            if await refresh_results(today, state, fetch_football_data, 1):
                get_state.cache_clear()
                await run_in_threadpool(get_state)
                log.info("Ratings rebuilt with fresh results")
        except Exception as error:          # never let the loop die
            log.warning("Results refresh failed: %s", error)
        await asyncio.sleep(REFRESH_EVERY_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Build the ratings in the background so the first page load is fast, and keep results fresh."""
    async def warm():
        try:
            await run_in_threadpool(get_state)
        except Exception as error:      # missing CSVs etc.: endpoints report it themselves
            app.state.warmup_error = str(error)
            log.warning("Ratings warm-up failed: %s", error)
    tasks = [asyncio.create_task(warm()), asyncio.create_task(refresh_loop())]
    yield
    for task in tasks:
        task.cancel()


def allowed_origins() -> list[str]:
    """Local dev origins plus your website. Add more with ALLOWED_ORIGINS="https://a.io,https://b.io"
    (or "*" to allow any site; fine because the API is read-only and has no secrets)."""
    origins = ["http://127.0.0.1:5500", "http://localhost:5500", "http://127.0.0.1:5501",
               "http://localhost:5501", "https://kingjah12-glitch.github.io"]
    extra = [o.strip().rstrip("/") for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]
    return ["*"] if "*" in extra else origins + extra


app = FastAPI(
    title="Sports Buddy",
    description="Football market analysis and live scores.",
    version="1.2.0",
    lifespan=lifespan,
)

# Allow the local frontend to communicate with the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Register API routers
app.include_router(predictions.router)
app.include_router(live_scores.router)
app.include_router(matches.router)


@app.get("/")
def home():
    return {
        "app": "Sports Buddy",
        "status": "running",
        "message": "Welcome to Sports Buddy!",
    }


@app.get("/health")
def health_check():
    return {"status": "healthy"}


@app.get("/api/v1")
def api_info():
    return {
        "features": [
            "Football match analysis",
            "Goal market estimates",
            "Goal-market probabilities (V4 model) grouped by league",
            "Fair odds and value check against bookmaker prices",
            "No-bet recommendations",
            "Live scores",
        ]
    }


@app.get("/status", tags=["System"])
def status():
    """Plain-language health report: is the history, the model and the API key in place?"""
    from app.config import API_FOOTBALL_KEY
    from app.services import ratings_store
    state = ratings_store._state
    report = {
        "api_football_key_configured": bool(API_FOOTBALL_KEY),
        "history_and_ratings_ready": state is not None,
        "warmup_error": getattr(app.state, "warmup_error", None),
    }
    if state is not None:
        report.update({
            "data_through": str(state.last_date),
            "competitions": len(state.teams_by_group),
            "model_v4_loaded": state.model is not None,
            "outcome_model_loaded": state.outcome_model is not None,
            "calibration_loaded": bool(state.calibrators),
        })
    else:
        report["note"] = ("Still starting up (building ratings takes ~10 seconds)"
                          if not report["warmup_error"] else "Start-up failed: see warmup_error")
    return report
