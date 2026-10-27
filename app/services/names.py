"""Single source of truth for team-name handling.

* normalize_name(): canonical key for a club name (accents, punctuation,
  club prefixes/suffixes such as FC/AFC/Calcio/SCO, founding years).
* resolve_key():    map a provider's spelling onto the key used in the CSV
  history of one competition (exact, token-containment, then fuzzy).
* data/team_aliases.json (optional) lets you add your own overrides without
  touching code: {"provider spelling": "csv spelling", ...}
"""
import difflib
import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

_PREFIXES = [
    ("1", "fsv"), ("1", "fc"), ("1", "fcn"),
    ("fc",), ("afc",), ("sc",), ("ssc",), ("sv",), ("fsv",), ("tsv",),
    ("vfb",), ("vfl",), ("ssv",), ("ac",), ("as",), ("us",), ("cf",),
    ("rc",), ("ca",), ("rcd",), ("tsg",), ("aj",), ("acf",),
    ("olympique",), ("stade",), ("ogc",),
]
_SUFFIXES = {"fc", "afc", "cf", "sc", "ud", "sco", "calcio", "bc", "ac",
             "cfc", "bsc", "osc", "fk"}

# provider spelling (already normalised) -> CSV spelling
ALIASES = {
    "bayern munchen": "bayern munich",
    "manchester united": "man united",
    "manchester city": "man city",
    "paris saint germain": "paris sg",
    "borussia monchengladbach": "m gladbach",
    "borussia dortmund": "dortmund",
    "bayer leverkusen": "leverkusen",
    "eintracht frankfurt": "ein frankfurt",
    "cologne": "koln",
    "wolverhampton wanderers": "wolves",
    "tottenham hotspur": "tottenham",
    "newcastle united": "newcastle",
    "nottingham forest": "nott m forest",
    "west ham united": "west ham",
    "brighton hove albion": "brighton",
    "leeds united": "leeds",
    "atletico madrid": "ath madrid",
    "athletic club": "ath bilbao",
    "athletic bilbao": "ath bilbao",
    "espanyol barcelona": "espanol",
    "deportivo de a coruna": "la coruna",
    "internazionale": "inter",
    "inter milan": "inter",
    "sporting cp": "sp lisbon",
    "sporting braga": "sp braga",
    "braga": "sp braga",
    "bodoe glimt": "bodo glimt",
    "flamengo": "flamengo rj",
    "rennais": "rennes",
    "los angeles galaxy": "la galaxy",
    "new york red bulls": "new york rb",
}


@lru_cache(maxsize=1)
def _user_aliases() -> dict:
    path = Path(__file__).resolve().parents[2] / "data" / "team_aliases.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {_basic(k): _basic(v) for k, v in raw.items()}


def _basic(value) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def normalize_name(value) -> str:
    tokens = _basic(value).split()
    original = list(tokens)

    changed = True
    while tokens and changed:
        changed = False
        for prefix in _PREFIXES:
            n = len(prefix)
            if len(tokens) > n and tuple(tokens[:n]) == prefix:
                tokens = tokens[n:]
                changed = True
                break

    while len(tokens) > 1 and tokens[-1] in _SUFFIXES:     # "Arsenal FC", "Angers SCO"
        tokens.pop()

    no_years = [t for t in tokens if not re.fullmatch(r"\d{2,4}", t)]
    if no_years:                                           # "Mainz 05", "Como 1907"
        tokens = no_years

    if not tokens:                                         # name was only a prefix
        tokens = original

    key = " ".join(tokens)
    return _user_aliases().get(key) or ALIASES.get(key, key)


def _tok_eq(a: str, b: str) -> bool:
    return a == b or (min(len(a), len(b)) >= 5
                      and difflib.SequenceMatcher(None, a, b).ratio() >= 0.85)


def resolve_key(query_key: str, candidates):
    """Best matching candidate key for query_key, or None.

    1. exact; 2. a candidate whose every word appears in the query
    ("sociedad" in "real sociedad san sebastian") - only if unambiguous;
    3. close fuzzy match on the whole string.
    """
    if query_key in candidates:
        return query_key

    q_tokens = query_key.split()
    hits = []
    for cand in candidates:
        c_tokens = cand.split()
        if c_tokens and all(any(_tok_eq(ct, qt) for qt in q_tokens) for ct in c_tokens):
            hits.append(cand)
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        # Prefer candidates whose words match the query EXACTLY (so "seville"
        # does not tie "betis" with "sevilla"), then the most specific name.
        def rank(c):
            toks = c.split()
            return (-sum(t in q_tokens for t in toks), -len(toks), -len(c))
        hits.sort(key=rank)
        if rank(hits[0]) != rank(hits[1]):
            return hits[0]
        return None                         # genuinely ambiguous -> do not guess

    close = difflib.get_close_matches(query_key, list(candidates), n=1, cutoff=0.86)
    return close[0] if close else None
