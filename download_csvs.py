
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

DATA_DIR = Path("data/historical/raw")
DATA_DIR.mkdir(parents=True, exist_ok=True)

# European leagues: codes used by football-data.co.uk.
EUROPEAN_LEAGUES = {
    "E0": "England_Premier_League",
    "E1": "England_Championship",
    "E2": "England_League_One",
    "E3": "England_League_Two",
    "EC": "England_National_League",
    "SC0": "Scotland_Premiership",
    "SC1": "Scotland_Championship",
    "SC2": "Scotland_League_One",
    "SC3": "Scotland_League_Two",
    "D1": "Germany_Bundesliga",
    "D2": "Germany_Bundesliga_2",
    "I1": "Italy_Serie_A",
    "I2": "Italy_Serie_B",
    "SP1": "Spain_La_Liga",
    "SP2": "Spain_Segunda",
    "F1": "France_Ligue_1",
    "F2": "France_Ligue_2",
    "N1": "Netherlands_Eredivisie",
    "B1": "Belgium_Pro_League",
    "P1": "Portugal_Primeira_Liga",
    "T1": "Turkey_Super_Lig",
    "G1": "Greece_Super_League",
}

# Extra leagues: one CSV per country, with seasons combined.
EXTRA_LEAGUES = {
    "ARG": "Argentina",
    "AUT": "Austria",
    "BRA": "Brazil",
    "CHN": "China",
    "DNK": "Denmark",
    "FIN": "Finland",
    "IRL": "Ireland",
    "JPN": "Japan",
    "MEX": "Mexico",
    "NOR": "Norway",
    "POL": "Poland",
    "ROU": "Romania",
    "RUS": "Russia",
    "SWE": "Sweden",
    "SWZ": "Switzerland",
    "USA": "USA_MLS",
}

# Seasons 2015/16 through 2025/26.
SEASONS = [
    f"{year}{(year + 1) % 100:02d}"
    for year in range(15, 27)
]

BASE_URL = "https://www.football-data.co.uk"
downloaded = 0
skipped = 0
failed = []

def download_csv(url, destination):
    request = Request(
        url,
        headers={"User-Agent": "SportsBuddyHistoricalData/1.0"},
    )
    with urlopen(request, timeout=30) as response:
        content = response.read()

    if len(content) < 50 or b"," not in content[:3000]:
        raise ValueError("Response is empty or does not look like CSV")

    destination.write_bytes(content)

# Download European leagues by season.
for season in SEASONS:
    for code, name in EUROPEAN_LEAGUES.items():
        filename = f"{name}_{season}.csv"
        destination = DATA_DIR / filename

        if destination.exists() and destination.stat().st_size > 100:
            skipped += 1
            continue

        url = f"{BASE_URL}/mmz4281/{season}/{code}.csv"

        try:
            download_csv(url, destination)
            downloaded += 1
            print(f"Downloaded: {filename}")
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            failed.append((filename, str(exc)))
            print(f"Unavailable: {filename}")

# Download additional-country archives.
for code, name in EXTRA_LEAGUES.items():
    filename = f"{name}_all_seasons.csv"
    destination = DATA_DIR / filename

    if destination.exists() and destination.stat().st_size > 100:
        skipped += 1
        continue

    url = f"{BASE_URL}/new/{code}.csv"

    try:
        download_csv(url, destination)
        downloaded += 1
        print(f"Downloaded: {filename}")
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        failed.append((filename, str(exc)))
        print(f"Unavailable: {filename}")

print("\n========== DOWNLOAD SUMMARY ==========")
print(f"Downloaded: {downloaded}")
print(f"Already present: {skipped}")
print(f"Unavailable/failed: {len(failed)}")

if failed:
    print("\nFiles to check or retry:")
    for filename, reason in failed:
        print(f"- {filename}: {reason}")
