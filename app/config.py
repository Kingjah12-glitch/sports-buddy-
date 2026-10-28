
import os
from pathlib import Path
from dotenv import load_dotenv

# Locate the .env file in the project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

load_dotenv(ENV_FILE, override=True)

API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", "").strip()

API_FOOTBALL_BASE_URL = os.getenv(
    "API_FOOTBALL_BASE_URL",
    "https://v3.football.api-sports.io",
).strip()
