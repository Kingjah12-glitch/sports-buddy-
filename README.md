# Sports Buddy

Football goal-market and result probabilities for 40 competitions, with a **Suggested picks** panel that ranks the
most likely options across every competition on the day. Probabilities come from a walk-forward model
(team ratings + form + a logistic layer) trained on ~10 years of results.

> Honest note: in backtests the bookmakers' own prices were at least as accurate as this model, and betting its
> "edge" lost money on average. Treat probabilities as a reference, not a tip. Never stake more than you can afford to lose.

## Make the site talk to a live API (recommended)
GitHub Pages can only host static files, so the model runs on a small free server that the site calls:
1. Sign in at render.com with GitHub > **New + > Blueprint** > pick this repo (it reads `render.yaml`).
2. When asked, type your `API_FOOTBALL_KEY` (it stays in Render, never in the repo). Deploy.
3. Copy the service address, e.g. `https://sports-buddy-api.onrender.com`.
4. In your repo edit `docs/config.js` to: `window.SB_CONFIG = { apiBase: "https://sports-buddy-api.onrender.com", dataBase: "data" };`
5. Open your site. Each visit asks the API for that day's matches, predicts every covered competition and builds the
   Suggested picks list (3 picks on a quiet day, 15 on a busy one: it shows whatever clears your probability setting).

Notes: the free server sleeps when idle, so the first visit can take about a minute ("Waking up the server...");
if it is unreachable the page falls back to the saved files from the daily workflow. Answers are cached for
10 minutes, so visitors cannot use up your API-Football quota (about 1 call per day viewed).
The server also refreshes yesterday's results every 6 hours by itself.

## Use it as a website with saved data only (no server)
1. Push this folder to a GitHub repository (keep `data/historical/raw/`, it is the model's history; `.env` is ignored).
2. Repo **Settings > Secrets and variables > Actions > New secret**: name `API_FOOTBALL_KEY`, value = your key.
3. Repo **Settings > Pages**: deploy from branch `main`, folder `/docs`.
4. **Actions > Daily predictions > Run workflow** once. After that it runs every morning by itself
   (refreshes yesterday's results, predicts today and tomorrow, scores yesterday, updates `docs/`).
5. Open `https://<your-username>.github.io/<repo>/`.

The site is static: it reads `docs/data/<date>.json`. Odds you type are stored in your own browser.

## Run it on your computer (optional)
    pip install -r requirements-dev.txt
    uvicorn app.main:app --reload          # then open frontend/index.html with VS Code Live Server
    python build_site.py                   # regenerate docs/ by hand
    python today.py                        # command-line table
    python score_day.py --date YYYY-MM-DD  # compare saved predictions with results
    python -m pytest -q                    # tests
    python backtest_v4.py                  # re-train + honest backtest report

## Files you may want to edit
- `data/team_aliases.json`: `{"provider spelling": "csv spelling"}` when a team name is not recognised.
- `data/today/fixtures_<date>.csv`: extra fixtures, e.g. Champions League with `PH,PD,PA` win percentages.
