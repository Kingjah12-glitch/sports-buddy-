# Sports Buddy - update 9 (live API hosting)

- The page calls a hosted API for the day's fixtures + predictions and builds the Suggested picks list from it;
  if the API is unreachable (or asleep for more than ~70 s) it falls back to the saved files in docs/data.
- `render.yaml`: one-click free hosting blueprint (see README: "Make the site talk to a live API").
- CORS now allows https://kingjah12-glitch.github.io (add more with the ALLOWED_ORIGINS environment variable).
- 10-minute cache on /api/v1/predictions/day so visitors cannot exhaust the API-Football quota.
- The server refreshes yesterday's results every 6 hours and rebuilds the ratings itself.
- build_site.py never overwrites docs/config.js once you have edited it.
- "Waking up the server..." message while a sleeping free server starts.
- Peak memory 214 MB (fits the 512 MB free tier). Tests: 34.

---

# Sports Buddy - update 8 (suggested picks + website mode)

## Test it today (two ways)
A) Live server:   pip install -r requirements-dev.txt ; uvicorn app.main:app --reload
                  then open frontend/index.html with VS Code Live Server and press "Load matches".
B) Static site:   python build_site.py          (uses your API key from .env; writes docs/data/<date>.json)
                  then serve docs/ (e.g. `python -m http.server --directory docs`) and open http://localhost:8000
For GitHub Pages + daily auto-updates see README.md (secret API_FOOTBALL_KEY, Pages from main /docs, run the workflow once).

## What's new
- **Suggested picks panel** (top of the page): the best option of every match across ALL competitions on the day,
  filtered by a minimum-probability slider (default 80%) and market checkboxes, sortable by probability, gap to
  your odds, or kickoff; one row per match; type your bookmaker odds to see the gap; "Copy list" button.
  It says plainly that most likely is not best value (backtests: safest picks lost ~5% after margin).
- **Website mode (no server, no terminal)**: build_site.py writes the same JSON the API returns into docs/data/;
  the page reads it when no server is configured, or when the server is down. config.js switches modes.
  .github/workflows/daily.yml refreshes results, rebuilds the site, scores yesterday and commits, every morning.
- Kickoff times now show in the viewer's own time zone.
- Shared code: app/services/day_payload.py (API and site builder use the same function).
- Tests: 29.

Not verified here: the GitHub Action itself and live API-Football calls (no network access from my build
environment). Everything else was run, including the page in a headless browser in all three modes.

---

# Sports Buddy - update 7 (all leagues + daily scorecard)

## New: compare predictions with the actual results, automatically
    python today.py --fixtures-file ... / python today.py      (morning: saves data/today/predictions_<date>.csv)
    python today.py --refresh-results                          (next day: pulls yesterday's finished matches)
    python score_day.py --date 2026-10-24                      (scores that day, appends to data/tracking/scorecard.csv)
The scorecard keeps a running total (hit rates, Brier vs a league-average guess, system-pick hit rate), so you
judge the model on hundreds of matches rather than one day. Saturday 24 Oct is already in it (22 matches).

## Not just the top 5
The history covers 40 competitions (Eredivisie, Primeira Liga, Super Lig, Belgian/Scottish/Greek/Austrian/Swiss
leagues, Championship / League One / League Two / National League, Bundesliga 2, Ligue 2, Serie B, Segunda,
Brazil, Argentina, Mexico, Japan, China, MLS, the Nordic leagues ...). `python today.py` (live API, no file) and
the web page already predict every covered fixture of the day; only the six leagues in my own results feed were
shown in the chat so far. Fixed: "2. Bundesliga" was mapped to the Bundesliga; Romania "Liga I" was not recognised.
Tests: 28.

## Is the model better outside the top 5?  (held-out matches, 2022-07 onward, Over 2.5 vs bookmaker)
Top 5 leagues:  model 0.2413 vs bookmaker 0.2386 (gap +0.0027).  All other leagues: 0.2450 vs 0.2428 (+0.0022).
Betting the model's edge lost in both groups (top 5: -13% / -7%, others: -4% / -14%). No sign that smaller
leagues are easier to beat; more leagues = more matches to analyse, not a proven edge.

---

# Sports Buddy - update 6 (win-or-draw + options list + system pick)

## Run Saturday's card
    python today.py --fixtures-file data/today/fixtures_2026-10-24.csv --date 2026-10-24
or start the API, open the page and pick 2026-10-24 (live fixtures + the file's cross-league games).
Kickoffs are shown in your browser's time zone; matches after midnight your time belong to the next day.

## What's new
- **Match-result model** (home / draw / away): multinomial logistic on the V4 features, stored as JSON
  (`data/models/model_outcome.json`, rebuilt by `python backtest_v4.py`). Falls back to a Poisson 1X2
  if the file is missing. Champions League / cross-league games use the supplied win probabilities.
- **New markets**: Home win or draw (1X), Away win or draw (X2), Under 2.5 - next to Over 1.5 / Over 2.5.
- **Options list on every card**: all five markets ranked by probability with fair odds, a box for YOUR
  bookmaker odds on each (gap shown in percentage points, remembered per match), a "system pick" tag on
  the most likely one, and a line naming the most likely goals market and the most likely result market.
- `today.py` table now shows 1X / X2 and the system pick.
- Tests: 26.

## What the backtest says (31,327 test matches with odds, nothing tuned on them)
- Result model: Brier 0.6096 vs 0.6126 (plain Poisson) and 0.6495 (frequency baseline); bookmaker 0.5966.
- Its win-or-draw probabilities are well calibrated (e.g. predicted 75% -> happened 74.9%).
- Betting them still loses: "safest pick" (higher of 1X / X2) hit 75.6% and returned -4.9% (+/-0.6%);
  1X on every match -5.9%; model "edge" bets -10% to -12%. Prices derived from 1X2 odds, so optimistic.
  A high hit rate is not profit: short odds mean one loss wipes out several wins.

---

# Sports Buddy - update 5 (newly promoted teams are no longer skipped)

- Live predictions now accept teams with as little as ~3 effective matches of history in the league
  (before: refused below 6, e.g. Coventry vs Tottenham on 19 Oct got no prediction). Such matches are flagged
  `data_quality = LOW`. Backed by a test on 807 out-of-sample matches (2022+) with 3-6 matches of history:
  2.67 goals predicted vs 2.71 actual, and no worse than teams with more history.
  Backtests keep their original cutoff of 6 so earlier results stay comparable.
- Tests: 23.

---

# Sports Buddy - update 4 (Champions League / cross-league mode)

## Run today's Champions League slate
    python today.py --fixtures-file data/today/fixtures_2026-10-20.csv --date 2026-10-20
or start the API + open the page and pick 2026-10-20: cross-league games from that file are merged
into the live fixtures and shown on their own "Champions League" tab.
Fixtures-file format for cross-league games: Date,Time(UTC),Country,League,Home,Away,PH,PD,PA
(PH/PD/PA = home/draw/away win % from any source, e.g. your bookmaker's 1X2 odds converted to %).

## What's new
- `app/services/cross_league.py` + `RatingsState.predict_cross_league`: teams from DIFFERENT leagues can't be
  rated against each other from domestic results, so each team keeps its own-league attack/defence rating
  and the supplied win probabilities set the strength gap. Over 1.5 / 2.5 come from the adjusted total.
  Validated on domestic matches using their real 1X2 odds (Over 2.5 Brier 0.2442 vs 0.2446 ratings-only;
  bookmaker's own O/U 0.2419). NOT validated on Champions League matches themselves.
- Cards show a "cross-league estimate" badge (or "rough cross-league" when a club is outside the history,
  e.g. Slavia Prague / Sabah / Slovan Bratislava) and an explanatory note.
- Loader now also reads 1X2 odds (used for the validation above).
- Tests: 22 (python -m pytest -q).

# Sports Buddy - update 3 (V4 model + league-by-league frontend)

## Install
1. Extract the zip into the folder that contains `sports buddy`, choose Replace.
   (Your `.env`, `recent_results.csv` and `data/team_aliases.json` are NOT in this zip, so they stay yours.)
2. `pip install -r requirements-dev.txt`
3. `python -m pytest -q`                      -> 19 passed
4. `python backtest_v4.py`                    -> ~2 min, refreshes data/models/model_v4.json + report
5. `uvicorn app.main:app --reload`, then open frontend/index.html with VS Code Live Server
   (the API allows ports 5500/5501). Pick a date and press "Load matches".

## What's new
- **Frontend**: one tab per league (Premier League, La Liga, ...) with a match count; each card shows
  kickoff, expected goals, calibrated P(Over 1.5 / 2.5) with probability bars and fair odds, a
  "limited history" badge, and two boxes where you type your bookmaker's odds to see the gap in
  percentage points (remembered per match in your browser).
- **`GET /api/v1/predictions/day?date=YYYY-MM-DD`**: every covered match of the day, grouped by league.
  Uses API-Football and automatically falls back to `data/today/fixtures_<date>.csv` if the live API
  is unavailable (e.g. free plan date limits). `?source=file` or `?source=api` forces one.
- **V4 model** (`features.py`, `model_v4.py`, `backtest_v4.py`): V3 ratings + short-term form +
  per-team over/under tendencies, combined by a regularised logistic model stored as JSON.
  Falls back to V3 automatically if `model_v4.json` is missing.
- Ratings now build in the background when the server starts (first page load is fast) with a lock.
- `today.py` shares its code with the web endpoint (`app/services/daily.py`).
- `pytest.ini` hides a harmless library warning.

## What the V4 backtest says (51,092 test matches, nothing tuned on them)
Over 2.5 Brier: baseline 0.2472 -> V3 0.2437 -> V4 0.2430 (bookmaker 0.2419).
Blending V4 with the bookmaker's price adds nothing (weight on V4 -0.07). Betting V4's "edge" lost money
(-2% to -25% depending on odds and threshold), and a pick-on-one-period / confirm-on-another search across
44 league-and-side combinations found 0 that held up. V4 is a small, honest accuracy gain - not an edge.

---

# Sports Buddy - update 2 (matches-of-the-day release)

## Run it today
    pip install -r requirements-dev.txt
    python -m pytest -q                                   # 14 passed
    python today.py --refresh-results                     # uses your API-Football key
    python today.py --odds my_odds.csv                    # optional: Home,Away,over_1_5,over_2_5
No API quota/key handy? `python today.py --fixtures-file data/today/fixtures_2026-10-18.csv`
(today's 20 matches are included, in the same format you can write yourself).
Times print in Africa/Lagos; change with `--tz`.

## What changed
- **Team-name matching** (was matching only 5 of today's 20 fixtures, now 20/20): suffix/number
  stripping (FC, AFC, SCO, Calcio, "1907", "05"...), word-containment + fuzzy matching inside the
  right competition, exact-word priority ("Seville" no longer ties Betis with Sevilla). Add your own
  fixes in `data/team_aliases.json`:  {"provider spelling": "csv spelling"}.
- **Results overlay** `data/historical/recent_results.csv`: the downloaded CSVs lag by a day or two;
  results in this file (Oct 17 included) feed the ratings and can never be double counted.
  `python today.py --refresh-results` fills it from API-Football (last 3 days, 3 requests).
- **`today.py`**: one command -> table of xG, calibrated P(Over 1.5 / 2.5), fair odds, data-quality flag,
  optional edge vs YOUR bookmaker odds; saves data/today/predictions_<date>.csv.
- `data_quality: LOW` flag when a team has < 15 effective matches of top-flight history.
- Strict competition coverage: an "Egypt Premier League" fixture is no longer mistaken for England.
- Backtest re-run after these changes: identical conclusions (V3 calibrated Brier 0.2437 / 0.1829).

Not verified from the build environment: live API-Football calls (no network there). The parsing and
refresh logic is unit-tested against the documented response shape; if a call fails, please paste me the error.

---

# Sports Buddy - update notes

## How to install this update
1. Extract this zip **into the folder that contains your `sports buddy` folder**
   and choose "Replace/overwrite" when asked. Your `.env`, `.venv` and
   `data/historical/raw` are untouched (they are not in the zip).
2. `pip install -r requirements-dev.txt`
3. `python -m pytest -q`            (should say 10 passed)
4. `python backtest_v3.py`          (about 1-2 minutes; rewrites data/models + report)
5. `uvicorn app.main:app --reload`  (first fixture request takes ~10 s to build ratings)

## What changed
**New (V3 model)**
- `backtest_v3.py` - walk-forward backtest with a held-out test period (after 2022-06-30),
  parameter tuning and calibration on train only, comparison against the bookmakers'
  own Over 2.5 price, and ROI with 95% confidence intervals.
- `app/services/ratings.py` - shrunk, time-decayed attack/defence ratings that carry over
  between seasons (replaces 5-match averages).
- `app/services/calibration.py`, `market_analyzer_v3.py`, `ratings_store.py`.
- `data/models/` - calibration + chosen parameters (regenerated by `backtest_v3.py`).

**Fixed**
- `.env` key was shipped in the archive -> `.env` is no longer included; `.env.example` filled in.
- `predictions.py`: removed unreachable duplicate block and stray import; fixture endpoint uses V3.
- `/value-check` now accepts 0.62 or 62 (it used to reject the percentages `/analyze` returns).
- `normalize_name` crash on empty names; one shared normaliser (`names.py`) used everywhere.
- Latin-1 CSVs are now read instead of silently skipped; the 16 extra-country files
  (Brazil, MLS, Japan, ...) are now included (the old code could not read their columns).
- `csv_history.get_team_form` is cached and no longer re-reads every CSV per call.
- `.gitignore` excludes the large generated result CSVs.

**Kept as-is**: `backtest.py` / `backtest_v2.py` (only the encoding + name fixes), the frontend,
`matches.py`, `live_scores.py`.
