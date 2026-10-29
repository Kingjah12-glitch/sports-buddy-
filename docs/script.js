const CONFIG = window.SB_CONFIG || { apiBase: "http://127.0.0.1:8000", dataBase: "data" };
const API_BASE = CONFIG.apiBase;           // "" = static website (no server)
const DATA_BASE = CONFIG.dataBase || "data";

class ApiError extends Error {}
class ServerDown extends Error {}      // the hosted server did not answer at all

const API_TIMEOUT_MS = 70000;     // free hosting can need ~1 minute to wake up
const HEALTH_TIMEOUT_MS = 8000;

async function fetchWithTimeout(url, ms) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), ms);
    try {
        return await fetch(url, { signal: controller.signal });
    } finally {
        clearTimeout(timer);
    }
}

const dateInput = document.getElementById("match-date");
const matchesContainer = document.getElementById("matches");
const tabsContainer = document.getElementById("league-tabs");
const summaryBar = document.getElementById("summary");
const extras = document.getElementById("extras");
const suggestionsPanel = document.getElementById("suggestions");
const sgMin = document.getElementById("sg-min");
const sgMinOut = document.getElementById("sg-min-out");
const sgMarkets = document.getElementById("sg-markets");
const sgSort = document.getElementById("sg-sort");
const sgList = document.getElementById("sg-list");
const sgCount = document.getElementById("sg-count");
const sgPlayed = document.getElementById("sg-played");
const message = document.getElementById("message");
const statusText = document.getElementById("api-status");
const statusDot = document.getElementById("status-dot");

let leagues = [];
let activeKey = null;
let currentDate = null;

function localDateString() {
    const now = new Date();
    const y = now.getFullYear();
    const m = String(now.getMonth() + 1).padStart(2, "0");
    const d = String(now.getDate()).padStart(2, "0");
    return `${y}-${m}-${d}`;
}

function browserTimeZone() {
    try {
        return Intl.DateTimeFormat().resolvedOptions().timeZone || "Africa/Lagos";
    } catch {
        return "Africa/Lagos";
    }
}

// Did this option come true? Only known once the match has finished.
function optionResult(match, key) {
    if (match.status !== "finished" || !match.score) return null;
    const h = match.score.home, a = match.score.away, total = h + a;
    switch (key) {
        case "over_1_5_goals": return total >= 2;
        case "over_2_5_goals": return total >= 3;
        case "under_2_5_goals": return total <= 2;
        case "home_or_draw": return h >= a;
        case "away_or_draw": return a >= h;
        default: return null;
    }
}

function resultMark(match, key) {
    const result = optionResult(match, key);
    if (result === null) return null;
    return el("span", result ? "res-hit" : "res-miss", result ? "✓" : "✗");
}

function statusChip(match) {
    if (match.status === "live") {
        const score = match.score ? ` ${match.score.home}–${match.score.away}` : "";
        return el("span", "chip chip-live", `LIVE${score}`);
    }
    if (match.status === "finished" && match.score) {
        return el("span", "chip chip-ft", `FT ${match.score.home}–${match.score.away}`);
    }
    return null;
}

function formatKickoff(match) {
    if (match.kickoff_iso) {
        const when = new Date(match.kickoff_iso);
        if (!Number.isNaN(when.getTime())) {
            return when.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
        }
    }
    return match.kickoff;
}

// Small DOM helper: always textContent, never innerHTML.
function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
}

async function checkAPI() {
    if (API_BASE) {
        try {
            const response = await fetchWithTimeout(`${API_BASE}/health`, HEALTH_TIMEOUT_MS);
            if (!response.ok) throw new Error("Health check failed");
            statusText.textContent = "API connected";
            statusDot.style.background = "#22c55e";
            return;
        } catch {
            /* fall through: try the saved data */
        }
    }
    try {
        const response = await fetch(`${DATA_BASE}/index.json`);
        if (!response.ok) throw new Error("no index");
        const index = await response.json();
        const stamp = (index.generated_at || "").replace("T", " ").replace("Z", " UTC").slice(0, 20);
        statusText.textContent = API_BASE ? "API offline, using saved data" : `Saved data, updated ${stamp}`;
        statusDot.style.background = API_BASE ? "#f59e0b" : "#22c55e";
    } catch {
        statusText.textContent = API_BASE ? "API unavailable" : "No data published yet";
        statusDot.style.background = "#ef4444";
    }
}

// ---------------------------------------------------------------- odds memory
function oddsKey(match) {
    return `sb_odds:${currentDate}:${match.home}|${match.away}`;
}

function loadOdds(match) {
    try {
        return JSON.parse(localStorage.getItem(oddsKey(match))) || {};
    } catch {
        return {};
    }
}

function saveOdds(match, odds) {
    try {
        localStorage.setItem(oddsKey(match), JSON.stringify(odds));
    } catch {
        /* storage unavailable: odds simply are not remembered */
    }
}

// Edge in percentage points between our probability and the bookmaker's implied one.
function describeEdge(probability, oddsValue) {
    const odds = parseFloat(oddsValue);
    if (!(odds > 1)) return { text: "enter odds", cls: "edge-none" };
    const edge = probability - 100 / odds;
    if (edge >= 5) return { text: `+${edge.toFixed(1)} pp (unproven)`, cls: "edge-pos" };
    if (edge >= 0) return { text: `+${edge.toFixed(1)} pp, too small`, cls: "edge-flat" };
    return { text: `${edge.toFixed(1)} pp, no value`, cls: "edge-neg" };
}

// ---------------------------------------------------------------- rendering
function optionRow(match, option, saved, isPick, onChange) {
    const row = el("div", `option${isPick ? " option-pick" : ""}`);

    const head = el("div", "option-head");
    const name = el("span", "option-label", option.label);
    if (isPick) name.appendChild(el("span", "pick-tag", "system pick"));
    const valueBox = el("span", "option-value", `${option.probability.toFixed(1)}%`);
    const mark = resultMark(match, option.key);
    if (mark) valueBox.appendChild(mark);
    head.append(name, valueBox);

    const track = el("div", "bar-track");
    const fill = el("div", "bar-fill");
    fill.style.width = `${Math.max(0, Math.min(100, option.probability))}%`;
    track.appendChild(fill);

    const foot = el("div", "option-foot");
    foot.appendChild(el("span", "market-fair", `fair odds ${option.fair_odds.toFixed(2)}`));
    const input = el("input", "odds-input");
    input.type = "number";
    input.min = "1.01";
    input.step = "0.01";
    input.placeholder = "your odds";
    input.setAttribute("aria-label", `${option.label} bookmaker odds`);
    if (saved[option.key]) input.value = saved[option.key];
    const result = el("span", "edge");
    const refresh = () => {
        const d = describeEdge(option.probability, input.value);
        result.textContent = d.text;
        result.className = `edge ${d.cls}`;
        onChange();
    };
    input.addEventListener("input", () => {
        const current = loadOdds(match);
        current[option.key] = input.value;
        saveOdds(match, current);
        refresh();
    });
    foot.append(input, result);

    row.append(head, track, foot);
    return { row, input, option, refresh };
}

function matchCard(match) {
    const card = el("article", "match-card pred-card");

    const top = el("div", "mc-top");
    top.appendChild(el("span", "kick", formatKickoff(match)));
    const chip = statusChip(match);
    if (chip) top.appendChild(chip);
    const quality = match.data_quality || "OK";
    if (quality === "LOW") {
        const badge = el("span", "badge-low", "limited history");
        badge.title = match.data_quality_note || "One team has little recent history.";
        top.appendChild(badge);
    } else if (quality.startsWith("CROSS")) {
        const badge = el("span", "badge-cross", quality === "CROSS_LOW" ? "rough cross-league" : "cross-league estimate");
        badge.title = match.data_quality_note || "Teams from different leagues.";
        top.appendChild(badge);
    }

    const teams = el("div", "mc-teams");
    teams.append(el("div", "team", match.home), el("div", "vs", "vs"), el("div", "team", match.away));
    const note = quality.startsWith("CROSS") && match.data_quality_note
        ? el("p", "note", match.data_quality_note) : null;

    const xg = el("div", "xg");
    xg.append(
        el("span", "xg-label", "Expected goals"),
        el("span", "xg-value", `${match.xg.home.toFixed(1)} – ${match.xg.away.toFixed(1)}`),
        el("span", "xg-total", `total ${match.xg.total.toFixed(1)}`)
    );

    const o = match.outcomes;
    const outcomes = o ? el("div", "outcomes") : null;
    if (o) {
        outcomes.append(
            el("span", null, `Home ${o.home.toFixed(0)}%`),
            el("span", null, `Draw ${o.draw.toFixed(0)}%`),
            el("span", null, `Away ${o.away.toFixed(0)}%`)
        );
        outcomes.title = o.source === "supplied" ? "From the supplied win probabilities" : "Model estimate";
    }

    const saved = loadOdds(match);
    const options = match.options || [];
    const rows = options.map((opt, i) => optionRow(match, opt, saved, i === 0, () => updateBest()));
    const best = el("div", "best-line");

    function updateBest() {
        let top = null;
        for (const r of rows) {
            const odds = parseFloat(r.input.value);
            if (!(odds > 1)) continue;
            const edge = r.option.probability - 100 / odds;
            if (top === null || edge > top.edge) top = { edge, label: r.option.label };
        }
        if (top === null) {
            const goals = options.find((x) => x.key.includes("goals"));
            const result = options.find((x) => x.key.endsWith("_or_draw"));
            const fmt = (x) => `${x.label} (${x.probability.toFixed(0)}%)`;
            best.textContent = goals && result
                ? `Most likely goals market: ${fmt(goals)}. Most likely result market: ${fmt(result)}. Enter your odds to compare prices.`
                : "";
            best.className = "best-line";
        } else if (top.edge >= 5) {
            best.textContent = `Biggest gap to your odds: ${top.label} (+${top.edge.toFixed(1)} pp). Unproven: backtests showed such gaps lost money.`;
            best.className = "best-line best-gap";
        } else {
            best.textContent = "No option beats your bookmaker's price by a meaningful margin.";
            best.className = "best-line best-none";
        }
    }
    updateBest();

    card.append(top, teams, ...(note ? [note] : []), xg, ...(outcomes ? [outcomes] : []),
                ...rows.map((r) => r.row), best);
    return card;
}

function renderTabs() {
    tabsContainer.replaceChildren();
    for (const league of leagues) {
        const tab = el("button", `tab${league.key === activeKey ? " active" : ""}`);
        tab.type = "button";
        tab.setAttribute("aria-pressed", String(league.key === activeKey));
        tab.append(el("span", "tab-name", league.league),
                   el("span", "tab-country", league.country),
                   el("span", "tab-count", String(league.matches.length)));
        tab.addEventListener("click", () => {
            activeKey = league.key;
            renderTabs();
            renderMatches();
        });
        tabsContainer.appendChild(tab);
    }
}

function renderMatches() {
    matchesContainer.replaceChildren();
    const league = leagues.find((l) => l.key === activeKey);
    if (!league) return;
    for (const match of league.matches) matchesContainer.appendChild(matchCard(match));
}

function renderSummary(data) {
    const s = data.summary;
    summaryBar.replaceChildren();
    summaryBar.hidden = false;
    const live = data.source.startsWith("api-football");
    const flat = data.leagues.flatMap((l) => l.matches);
    const finished = flat.filter((m) => m.status === "finished").length;
    const liveNow = flat.filter((m) => m.status === "live").length;
    summaryBar.append(
        el("span", "pill", `${s.predicted} matches`),
        ...(finished || liveNow ? [el("span", "pill", `${finished} played${liveNow ? `, ${liveNow} live` : ""}`)] : []),
        el("span", "pill", `${s.leagues} league${s.leagues === 1 ? "" : "s"}`),
        el("span", "pill", `model ${data.model_version || "-"}`),
        el("span", "pill", `history through ${data.data_through}`),
        el("span", `pill ${live ? "pill-live" : "pill-file"}`, data.source === "api-football+file" ? "live + file fixtures" : live ? "live fixtures" : "offline fixtures file")
    );
    if (data.fallback_reason) {
        summaryBar.appendChild(el("span", "pill-note", `Live API unavailable: ${data.fallback_reason}`));
    }
}

function renderExtras(data) {
    extras.replaceChildren();
    const notes = [];
    if (data.unmatched.length) {
        notes.push(["Teams I could not match to the history (no prediction)",
                    data.unmatched.map((u) => `${u.league}: ${u.home} v ${u.away}`)]);
    }
    if (data.not_covered.length) {
        notes.push([`Other competitions not covered (${data.not_covered.length})`,
                    data.not_covered.map((n) => `${n.competition} (${n.matches})`)]);
    }
    for (const [title, items] of notes) {
        const details = el("details", "extra");
        details.appendChild(el("summary", null, title));
        const list = el("ul");
        for (const item of items) list.appendChild(el("li", null, item));
        details.appendChild(list);
        extras.appendChild(details);
    }
}

// ---------------------------------------------------------------- suggested picks
const MARKET_CHOICES = [
    ["over_1_5_goals", "Over 1.5"], ["over_2_5_goals", "Over 2.5"], ["under_2_5_goals", "Under 2.5"],
    ["home_or_draw", "Home or draw"], ["away_or_draw", "Away or draw"],
];
const enabledMarkets = new Set(MARKET_CHOICES.map(([key]) => key));
let currentSuggestions = [];

function buildMarketToggles() {
    sgMarkets.replaceChildren();
    for (const [key, label] of MARKET_CHOICES) {
        const wrap = el("label", "sg-check");
        const box = el("input");
        box.type = "checkbox";
        box.checked = enabledMarkets.has(key);
        box.addEventListener("change", () => {
            if (box.checked) enabledMarkets.add(key); else enabledMarkets.delete(key);
            renderSuggestions();
        });
        wrap.append(box, el("span", null, label));
        sgMarkets.appendChild(wrap);
    }
}

// Best enabled option of every match across ALL competitions, above the probability threshold.
function collectSuggestions() {
    const minimum = Number(sgMin.value);
    const items = [];
    for (const league of leagues) {
        for (const match of league.matches) {
            if (!sgPlayed.checked && match.status && match.status !== "upcoming") continue;
            let best = null;
            for (const option of match.options || []) {
                if (!enabledMarkets.has(option.key)) continue;
                if (!best || option.probability > best.probability) best = option;
            }
            if (best && best.probability >= minimum) items.push({ league, match, option: best });
        }
    }
    return items;
}

function sortSuggestions(items) {
    const mode = sgSort.value;
    const gap = (item) => {
        const odds = parseFloat(loadOdds(item.match)[item.option.key]);
        return odds > 1 ? item.option.probability - 100 / odds : -Infinity;
    };
    const when = (item) => item.match.kickoff_iso || item.match.kickoff;
    if (mode === "gap") items.sort((a, b) => gap(b) - gap(a) || b.option.probability - a.option.probability);
    else if (mode === "time") items.sort((a, b) => (when(a) < when(b) ? -1 : when(a) > when(b) ? 1 : 0));
    else items.sort((a, b) => b.option.probability - a.option.probability);
    return items;
}

function suggestionRow(item, rank) {
    const { league, match, option } = item;
    const li = el("li", "sg-item");
    li.appendChild(el("span", "sg-rank", String(rank)));

    const main = el("div", "sg-main");
    main.appendChild(el("div", "sg-match", `${match.home} v ${match.away}`));
    const meta = el("div", "sg-meta");
    meta.append(el("span", null, formatKickoff(match)), el("span", "sg-league", league.league));
    const sgChip = statusChip(match);
    if (sgChip) meta.appendChild(sgChip);
    const quality = match.data_quality || "OK";
    if (quality === "LOW") meta.appendChild(el("span", "badge-low", "limited history"));
    if (quality.startsWith("CROSS")) meta.appendChild(el("span", "badge-cross", "cross-league"));
    main.appendChild(meta);
    li.appendChild(main);

    const pick = el("div", "sg-pick");
    pick.append(el("div", "sg-pick-label", option.label),
                (() => {
                    const prob = el("div", "sg-pick-prob", `${option.probability.toFixed(1)}%`);
                    const m = resultMark(match, option.key);
                    if (m) prob.appendChild(m);
                    return prob;
                })(),
                el("div", "market-fair", `fair odds ${option.fair_odds.toFixed(2)}`));
    li.appendChild(pick);

    const oddsBox = el("div", "sg-odds");
    const input = el("input", "odds-input");
    input.type = "number";
    input.min = "1.01";
    input.step = "0.01";
    input.placeholder = "your odds";
    input.setAttribute("aria-label", `${option.label} odds for ${match.home} v ${match.away}`);
    const saved = loadOdds(match)[option.key];
    if (saved) input.value = saved;
    const result = el("span", "edge");
    const refresh = () => {
        const d = describeEdge(option.probability, input.value);
        result.textContent = d.text;
        result.className = `edge ${d.cls}`;
    };
    input.addEventListener("input", () => {
        const current = loadOdds(match);
        current[option.key] = input.value;
        saveOdds(match, current);
        refresh();
    });
    input.addEventListener("change", () => { if (sgSort.value === "gap") renderSuggestions(); });
    refresh();
    oddsBox.append(input, result);
    li.appendChild(oddsBox);
    return li;
}

function renderSuggestions() {
    if (!leagues.length) {
        suggestionsPanel.hidden = true;
        return;
    }
    suggestionsPanel.hidden = false;
    sgMinOut.textContent = `${sgMin.value}%`;
    currentSuggestions = sortSuggestions(collectSuggestions());
    sgList.replaceChildren();
    const comps = new Set(currentSuggestions.map((i) => i.league.key));
    const all = leagues.flatMap((l) => l.matches);
    const played = all.filter((m) => m.status && m.status !== "upcoming").length;
    const total = sgPlayed.checked ? all.length : all.length - played;
    if (!currentSuggestions.length && !sgPlayed.checked && played === all.length) {
        sgCount.textContent = `All ${all.length} match${all.length === 1 ? "" : "es"} today have started or finished. Tick "Include matches already played" to see how the picks did.`;
        return;
    }
    sgCount.textContent = currentSuggestions.length
        ? `${currentSuggestions.length} suggested pick${currentSuggestions.length === 1 ? "" : "s"} from ${total} matches in ${comps.size} competition${comps.size === 1 ? "" : "s"}`
        : `No option reaches ${sgMin.value}% (of ${total} matches). Lower the minimum or enable more markets.`;
    currentSuggestions.forEach((item, i) => sgList.appendChild(suggestionRow(item, i + 1)));
}

async function copySuggestions() {
    const lines = currentSuggestions.map((i) =>
        `${formatKickoff(i.match)} ${i.match.home} v ${i.match.away} - ${i.option.label} ${i.option.probability.toFixed(0)}% (fair odds ${i.option.fair_odds.toFixed(2)}) [${i.league.league}]`);
    const copyButton = document.getElementById("sg-copy");
    try {
        await navigator.clipboard.writeText(`Suggested picks ${currentDate}\n` + lines.join("\n"));
        copyButton.textContent = "Copied";
    } catch {
        copyButton.textContent = "Copy not allowed";
    }
    setTimeout(() => { copyButton.textContent = "Copy list"; }, 1500);
}

sgMin.addEventListener("input", renderSuggestions);
sgSort.addEventListener("change", renderSuggestions);
sgPlayed.addEventListener("change", renderSuggestions);
document.getElementById("sg-copy").addEventListener("click", copySuggestions);
buildMarketToggles();

async function fetchDay(date) {
    let serverProblem = null;
    if (API_BASE) {
        try {
            const url = new URL(`${API_BASE}/api/v1/predictions/day`);
            url.searchParams.set("date", date);
            url.searchParams.set("tz", browserTimeZone());
            const response = await fetchWithTimeout(url, API_TIMEOUT_MS);
            const data = await response.json();
            if (response.ok) {
                statusText.textContent = "API connected";
                statusDot.style.background = "#22c55e";
                return data;
            }
            const detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
            throw new ApiError(detail || `Request failed (${response.status})`);
        } catch (error) {
            if (error instanceof ApiError) throw error;      // server answered with an error: show it
            serverProblem = error.name === "AbortError"
                ? "did not answer within 70 seconds (it may be starting up or stopped)"
                : "could not be reached (it may be starting up or stopped, or the address in config.js is wrong)";
            statusText.textContent = "Server not answering";
            statusDot.style.background = "#ef4444";
            /* use the saved static data below if there is any */
        }
    }
    const response = await fetch(`${DATA_BASE}/${date}.json`);
    if (!response.ok) {
        if (serverProblem) {
            throw new ServerDown(`The prediction server ${serverProblem}, and there is no saved data for this date. ` +
                                 `Open ${API_BASE}/status in a new tab to check it`);
        }
        throw new Error(response.status === 404
            ? "No predictions have been published for this date yet"
            : `Request failed (${response.status})`);
    }
    return response.json();
}

let loadToken = 0;          // lets a newer request win over a slower older one

async function loadMatches() {
    const token = ++loadToken;
    matchesContainer.replaceChildren();
    tabsContainer.replaceChildren();
    extras.replaceChildren();
    summaryBar.hidden = true;
    suggestionsPanel.hidden = true;
    message.textContent = "Loading predictions...";
    currentDate = dateInput.value || localDateString();
    const slowTimer = API_BASE ? setTimeout(() => {
        message.textContent = "Waking up the server (free hosting sleeps when idle). This can take up to a minute...";
    }, 4000) : null;

    try {
        const data = await fetchDay(currentDate);
        clearTimeout(slowTimer);
        if (token !== loadToken) return;      // a newer request has taken over

        leagues = data.leagues || [];
        if (leagues.length === 0) {
            message.textContent = "No matches in the 40 covered competitions on this date (a cup or midweek gap?). Try the next day with the › button.";
            renderExtras(data);
            return;
        }
        if (!leagues.some((l) => l.key === activeKey)) activeKey = leagues[0].key;

        message.textContent = "";
        renderSummary(data);
        renderSuggestions();
        renderTabs();
        renderMatches();
        renderExtras(data);
    } catch (error) {
        clearTimeout(slowTimer);
        if (token !== loadToken) return;
        message.textContent = `Could not load predictions: ${error.message}.` +
            (API_BASE && !(error instanceof ServerDown) ? " Check that the FastAPI server is running." : "");
    }
}

function shiftDay(delta) {
    const base = dateInput.value ? new Date(`${dateInput.value}T12:00:00`) : new Date();
    base.setDate(base.getDate() + delta);
    const y = base.getFullYear(), m = String(base.getMonth() + 1).padStart(2, "0"), d = String(base.getDate()).padStart(2, "0");
    dateInput.value = `${y}-${m}-${d}`;
    loadMatches();
}

document.getElementById("prev-day").addEventListener("click", () => shiftDay(-1));
document.getElementById("next-day").addEventListener("click", () => shiftDay(1));
document.getElementById("load-matches").addEventListener("click", loadMatches);
dateInput.value = localDateString();
checkAPI();
loadMatches();
