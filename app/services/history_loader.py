"""Loads every football-data.co.uk CSV in data/historical/raw into one
chronological list of matches.

Handles both layouts:
  * per-season European files  (HomeTeam, AwayTeam, FTHG, FTAG, ...)
  * per-country "new" files    (Home, Away, HG, AG, League, ...)  <- these were
    silently ignored by the old backtests.
Also tolerates Latin-1 encoded files (the old code skipped those).
"""
import csv
import io
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from app.services.names import normalize_name, resolve_key

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = PROJECT_ROOT / "data" / "historical" / "raw"
RECENT_FILE = PROJECT_ROOT / "data" / "historical" / "recent_results.csv"

_DATE_FORMATS = ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d")
_SEASON_SUFFIX = re.compile(r"^(?P<group>.+)_(?P<season>\d{4})$")


def read_csv_rows(path: Path) -> list[dict]:
    """Read a CSV as dict rows; fall back to Latin-1 if it is not UTF-8."""
    raw = Path(path).read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    return list(csv.DictReader(io.StringIO(text, newline="")))


def open_csv(path):
    """Drop-in replacement for path.open(...) used by the old backtests."""
    raw = Path(path).read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    return io.StringIO(text, newline="")


def parse_date(value):
    value = str(value or "").strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _num(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 1.0 else None


def _first_odds(row, columns):
    for col in columns:
        if col in row:
            val = _num(row.get(col))
            if val is not None:
                return val
    return None


def _first_triplet(row, sets):
    """First complete (home, draw, away) decimal-odds triple found in a row."""
    for cols in sets:
        vals = [_num(row.get(c)) if c in row else None for c in cols]
        if all(v is not None for v in vals):
            return tuple(vals)
    return (None, None, None)


_ODDS_1X2 = (("AvgH", "AvgD", "AvgA"), ("BbAvH", "BbAvD", "BbAvA"), ("B365H", "B365D", "B365A"))


def _clean(row):
    """Strip the BOM that can stick to the first header name."""
    return {(k or "").lstrip("\ufeff\u00ef\u00bb\u00bf").strip(): v
            for k, v in row.items()}


@lru_cache(maxsize=2)
def load_all_matches(raw_dir: str | None = None) -> list[dict]:
    """Return completed matches sorted by date.

    Each item: date, day (ordinal), group (competition), home, away, hk, ak
    (normalised names), hg, ag, and optional over/under-2.5 odds
    (o_avg/u_avg/o_max/u_max).
    """
    folder = Path(raw_dir) if raw_dir else RAW_DIR
    if not folder.exists():
        raise FileNotFoundError(f"Historical CSV folder not found: {folder}")

    files = sorted(folder.glob("*.csv"))
    if not files:
        raise FileNotFoundError(f"No CSV files found in {folder}")

    matches, seen = [], set()

    for path in files:
        m = _SEASON_SUFFIX.match(path.stem)
        file_group = m.group("group") if m else None

        for raw_row in read_csv_rows(path):
            row = _clean(raw_row)

            home = (row.get("HomeTeam") or row.get("Home") or "").strip()
            away = (row.get("AwayTeam") or row.get("Away") or "").strip()
            try:
                hg = int(row.get("FTHG") if "FTHG" in row else row.get("HG"))
                ag = int(row.get("FTAG") if "FTAG" in row else row.get("AG"))
            except (TypeError, ValueError):
                continue                      # unplayed / malformed row

            match_date = parse_date(row.get("Date"))
            if not match_date or not home or not away or hg < 0 or ag < 0:
                continue

            if file_group:
                group = file_group
            else:
                country = (row.get("Country") or path.stem).strip()
                league = (row.get("League") or "").strip()
                group = re.sub(r"[^A-Za-z0-9]+", "_", f"{country}_{league}").strip("_")

            hk, ak = normalize_name(home), normalize_name(away)
            key = (group, match_date, hk, ak)
            if key in seen:
                continue
            seen.add(key)

            matches.append({
                "date": match_date,
                "day": match_date.toordinal(),
                "group": group,
                "home": home,
                "away": away,
                "hk": hk,
                "ak": ak,
                "hg": hg,
                "ag": ag,
                "o_avg": _first_odds(row, ("Avg>2.5", "BbAv>2.5")),
                "u_avg": _first_odds(row, ("Avg<2.5", "BbAv<2.5")),
                "o_max": _first_odds(row, ("Max>2.5", "BbMx>2.5")),
                "u_max": _first_odds(row, ("Max<2.5", "BbMx<2.5")),
                "x12": _first_triplet(row, _ODDS_1X2),
            })

    matches.extend(_overlay_matches(matches, seen))
    matches.sort(key=lambda x: x["day"])
    return matches


def _overlay_matches(matches, seen) -> list[dict]:
    """Results newer than the downloaded CSVs (data/historical/recent_results.csv).

    Columns: Date (YYYY-MM-DD), Competition (e.g. England_Premier_League),
    Home, Away, HG, AG. Team names may use the API provider's spelling; they are
    resolved onto the CSV spelling of that competition, and anything already in
    the CSVs is skipped, so the file can safely be re-generated.
    """
    if not RECENT_FILE.exists():
        return []
    teams = {}
    for m in matches:
        teams.setdefault(m["group"], set()).update((m["hk"], m["ak"]))

    added = []
    for raw_row in read_csv_rows(RECENT_FILE):
        row = _clean(raw_row)
        try:
            hg, ag = int(row["HG"]), int(row["AG"])
        except (KeyError, TypeError, ValueError):
            continue
        match_date = parse_date(row.get("Date"))
        group = (row.get("Competition") or "").strip()
        home, away = (row.get("Home") or "").strip(), (row.get("Away") or "").strip()
        if not (match_date and group and home and away):
            continue
        known = teams.get(group, set())
        hk = resolve_key(normalize_name(home), known) or normalize_name(home)
        ak = resolve_key(normalize_name(away), known) or normalize_name(away)
        key = (group, match_date, hk, ak)
        if key in seen:
            continue
        seen.add(key)
        added.append({
            "date": match_date, "day": match_date.toordinal(), "group": group,
            "home": home, "away": away, "hk": hk, "ak": ak, "hg": hg, "ag": ag,
            "o_avg": None, "u_avg": None, "o_max": None, "u_max": None,
            "x12": (None, None, None),
        })
    return added
