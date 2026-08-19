# Zuntra Lead Intelligence — Component Guide

This document explains how every part of the program works: what each folder does, how data moves between layers, and how the major flows (company search, lead investigation, people lookup) are implemented end to end.

---

## Table of contents

1. [System overview](#1-system-overview)
2. [How the layers connect](#2-how-the-layers-connect)
3. [Flask API (`ui/app.py`)](#3-flask-api-uiapppy)
4. [Web frontend (`front/`)](#4-web-frontend-front)
5. [Chrome extension (`extension/`)](#5-chrome-extension-extension)
6. [Company intelligence pipeline (`web scraper/`)](#6-company-intelligence-pipeline-web-scraper)
7. [Lead finder (`lead finder/`)](#7-lead-finder-lead-finder)
8. [LinkedIn profile scraper (`lead scraper/`)](#8-linkedin-profile-scraper-lead-scraper)
9. [Persistence layer (`web scraper/src/store.py`)](#9-persistence-layer-web-scrapersrcstorepy)
10. [Database schema (`supabase/schema.sql`)](#10-database-schema-supabaseschemasql)
11. [People lookup — full decision tree](#11-people-lookup--full-decision-tree)
12. [Environment variables and secrets](#12-environment-variables-and-secrets)
13. [Design patterns used throughout](#13-design-patterns-used-throughout)

---

## 1. System overview

Zuntra Lead Intelligence is a local-first research tool. You enter a company name, an email, or a person's name, and the app builds a structured dossier: identity, financials, filings, news, LinkedIn profiles, and contact details. Everything is orchestrated by a Flask server running on `http://127.0.0.1:5000`. The browser (web app or Chrome extension) talks only to Flask; Flask is the only component that reads and writes Supabase or local JSON files.

The system has four main capabilities:

| Capability | Entry point | Backend path |
|---|---|---|
| **Dashboard** | Browse tracked companies, bookmarks | `GET /api/reports`, `GET /api/bookmarks` |
| **Lead investigation** | Email → company dossier | `lead finder` → `web scraper` pipeline |
| **Company search** | Company name or ticker → full dossier | `web scraper/src/pipeline.py` |
| **People lookup** | Name/company/URL → LinkedIn search + scrape | `lead finder/linkedin_search.py` + `lead scraper/scraper.py` |

LinkedIn automation uses Playwright (headless Chromium). Company data comes from public APIs (Yahoo, Finnhub, Alpha Vantage, SEC EDGAR, NewsAPI, GNews, Wikipedia). Optional Groq LLM calls polish descriptions and filter news relevance.

---

## 2. How the layers connect

```
┌─────────────────────────────────────────────────────────────────┐
│  Browser                                                        │
│  front/index.html  OR  extension/sidepanel.html                 │
│  (vanilla JS SPA — state, SSE, render)                          │
└───────────────────────────┬─────────────────────────────────────┘
                            │ HTTP / SSE
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  Flask orchestrator (ui/app.py :5000)                           │
│  • Serves static SPA                                            │
│  • REST + SSE API endpoints                                     │
│  • Spawns subprocesses for Playwright / async pipeline          │
│  • Single client of store.py                                    │
└───────┬─────────────────┬──────────────────┬──────────────────┘
        │                 │                  │
        ▼                 ▼                  ▼
┌───────────────┐ ┌───────────────┐ ┌───────────────────────────┐
│ web scraper/  │ │ lead finder/  │ │ lead scraper/             │
│ pipeline.py   │ │ orchestrate   │ │ scraper.py + extract.py   │
│ adapters/*    │ │ linkedin_     │ │ auth.py + contacts.py     │
│ store.py      │ │ search.py     │ │                           │
└───────┬───────┘ └───────┬───────┘ └─────────────┬─────────────┘
        │                 │                       │
        └─────────────────┴───────────────────────┘
                            │
                            ▼
              ┌─────────────────────────────┐
              │ Supabase (Postgres + JSONB) │
              │ OR not to share/web scraper/│
              │   (local JSON fallback)     │
              └─────────────────────────────┘
```

**Key rule:** The browser never connects to Supabase. All persistence goes through `web scraper/src/store.py`, imported by Flask after adding `web scraper` to `sys.path`.

**Subprocess isolation:** Flask does not import Playwright directly for LinkedIn work. Instead it spawns child Python processes with inline `-c` scripts. This avoids blocking the Flask event loop, prevents sync/async conflicts, and makes it possible to kill entire browser process trees on cancel.

---

## 3. Flask API (`ui/app.py`)

Flask is the central orchestrator. On startup it loads `not to share/.env`, inserts `web scraper` on `sys.path`, and uses `not to share/.venv/Scripts/python.exe` for all subprocess calls.

### Static routes

| Route | Handler | Purpose |
|---|---|---|
| `/`, `/dashboard`, `/lead`, `/company`, `/people`, `/linkedin` | `index()` | Serves `front/index.html` for all SPA routes |
| `/css/*`, `/js/*` | `serve_css`, `serve_js` | Static assets from `front/` |

Hash-based routing (`#dashboard`, `#lead`, etc.) is handled entirely in the frontend; Flask always returns the same HTML shell.

### Company endpoints

| Method | Path | What it does |
|---|---|---|
| `POST` | `/api/company` | Runs `asyncio.run(run_pipeline(query))` synchronously; returns full dossier JSON |
| `GET` | `/api/company/stream?query=...` | **SSE stream** — emits progress events, then `{ done: true, dossier }`. Uses a background thread + `queue.Queue`. If dossier is fresh (< 6h) and passes quality checks, skips the pipeline entirely |
| `POST` | `/api/company/news` | Fetches news only via `fetch_company_news()` |
| `POST` | `/api/company/refresh` | Returns cached dossiers for bookmarked companies; triggers background lite refresh for stale ones (> 24h) |
| `GET` | `/api/reports` | `list_companies()` — all stored dossiers |
| `GET` | `/api/stats` | Company count |

**Company stream internals:**

1. Creates a per-request progress queue in `_progress_queues`.
2. Background thread calls `_fresh_company_dossier(query)` — if cached and fresh, emits one `complete` event and exits.
3. Otherwise sets `set_progress_callback()` and runs `run_pipeline`.
4. Generator reads from queue, yields `data: {json}\n\n` SSE frames until `done` or 120s timeout.

### Lead endpoints

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/lead/samples` | Loads sample leads from cookie snapshot files |
| `POST` | `/api/lead/parse` | Classifies an email (`classify_email`) without running pipelines |
| `POST` | `/api/lead/investigate` | Runs `run_lead_finder(email, no_scrape=True, no_search=True)` — company dossier only, 150s timeout |
| `POST` | `/api/lead/investigate/stop` | Kills `_lead_investigation_proc` via `_kill_process_tree()` |

The UI strips news from lead investigation results on the frontend. Users trigger news separately via **Look up news**.

### LinkedIn / People endpoints

| Method | Path | What it does |
|---|---|---|
| `POST` | `/api/linkedin/search` | **SSE** — people search OR cached profile return OR visual-only refresh (see §11) |
| `POST` | `/api/linkedin/search/stop` | Kills `_linkedin_search_proc` |
| `POST` | `/api/linkedin` | Sync scrape up to 5 profile URLs via embedded `_LI_RUNNER` script |
| `GET`/`POST` | `/api/linkedin/stream` | **SSE** — line-delimited JSON progress from scrape subprocess |
| `POST` | `/api/linkedin/scrape/stop` | Kills `_linkedin_scrape_proc` |
| `POST` | `/api/people/enrich` | Contact enrichment without Playwright (`enrich_profile` with hints only) |

### Workspace endpoints

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/workspace` | Returns bookmarks, leads, linkedin state from Supabase |
| `PUT` | `/api/workspace` | Saves workspace snapshot; syncs bookmarks to dedicated table |
| `GET` | `/api/bookmarks` | Lists bookmarked company keys |
| `POST` | `/api/bookmarks` | Adds a bookmark |
| `DELETE` | `/api/bookmarks/<key>` | Removes a bookmark |

### Embedded subprocess scripts

Flask does not import Playwright or the lead scraper directly. It formats Python scripts at runtime and passes them to subprocess:

| Script constant | Imports | Purpose |
|---|---|---|
| `_LI_RUNNER` | `lead scraper/src/scraper.run` | Profile scrape with `on_progress` JSON lines |
| `_LI_SEARCH` | `lead finder/src/linkedin_search.search_people_urls` | People search with progress callbacks |
| `_LI_ENRICH` | `lead scraper/src/contacts.enrich_profile` | Contact-only enrichment |
| `_LEAD_INVESTIGATE` | `lead finder/src/orchestrate.run_lead_finder` | Email → company pipeline |
| `_LEAD_PARSE` | `lead finder/src/email_parse.classify_email` | Email classification |

Each subprocess gets `PYTHONUNBUFFERED=1` and `HEADLESS=true` for LinkedIn runs.

### Concurrency control

Four locks protect against overlapping long-running jobs:

| Lock | Process variable | Stop endpoint |
|---|---|---|
| `_lead_investigation_lock` | `_lead_investigation_proc` | `/api/lead/investigate/stop` |
| `_linkedin_scrape_lock` | `_linkedin_scrape_proc` | `/api/linkedin/scrape/stop` |
| `_linkedin_search_lock` | `_linkedin_search_proc` | `/api/linkedin/search/stop` |
| `_bookmark_refresh_lock` | `_bookmark_refreshing: set[str]` | (background, no stop) |

Starting a new run always kills any in-flight process under the same lock first. On Windows, `_kill_process_tree()` uses `taskkill /F /T /PID`; elsewhere it uses `terminate()` then `kill()`.

### Helper functions

| Function | Role |
|---|---|
| `_people_hints(data)` | Normalizes `{ name, company, role, location, email, phone }` from request body |
| `_people_from_store(...)` | Wraps `find_people_for_query()` + `person_to_profile()` for cache lookups |
| `_friendly_cli_error(stderr, stdout, fallback)` | Converts Playwright timeout/auth errors into user-facing messages |
| `_last_json_line(stdout)` | Parses the last stdout line as JSON (subprocess result convention) |

---

## 4. Web frontend (`front/`)

The SPA is a single-page app with no framework. All logic lives in `front/js/app.js` (~2100 lines). CSS is in `front/css/style.css`.

### Global state

```javascript
state = {
  tab: 'dashboard',           // active tab
  leads: [],                  // lead investigation queue
  company: {                  // company search panel
    query, dossier, searching, progressPct, progressStep
  },
  linkedin: {                 // people lookup panel
    name, company, role, location, email, phone, url,
    profiles,                  // scraped profile cards
    candidateUrls, candidates, // search match cards
    searching, searched, matchesOpen,
    progressPct, progressStep,
    scraping, scrapePct, scrapeStep
  },
  reports: [],                // all company dossiers from /api/reports
  bookmarks: []               // pinned company keys
}
```

Active operation trackers (for cancellation):

- `activeLeadInvestigation` — `{ leadId, controller }`
- `activeLinkedinScrape` — `{ source, controller, stopped, finish }`
- `activePeopleSearch` — `{ controller, stopped }`

### Tabs

`switchTab(tab)` toggles `.panel` visibility, updates `history.replaceState(#tab)`, and calls `renderAll()`. Valid tabs: `dashboard`, `lead`, `company`, `people` (legacy `#linkedin` redirects to `people`).

On init: `loadWorkspace()` → `loadSampleLeads()` → `switchTab(initial)` → `loadReports()` → `refreshBookmarkedCompanies()`.

### Persistence

**sessionStorage** (`zuntraFrontUi`): Saves company dossier, reports, bookmarks, leads between page reloads. LinkedIn form fields are cleared from the snapshot for privacy; only the `searched` flag is kept.

**Remote workspace** (`PUT /api/workspace`): Debounced 300ms after every `saveState()`. Syncs bookmarks and leads to Supabase. On load, `loadWorkspace()` merges remote data and migrates any local-only bookmarks to the server.

### SSE consumption

**Company search** uses native `EventSource`:

```javascript
const es = new EventSource('/api/company/stream?query=' + encodeURIComponent(query));
es.onmessage = (e) => { /* update progress bar from msg.pct / msg.step */ };
// On done: fetch dossier via GET /api/reports and match by query
```

**People search and scrape** use manual SSE parsing (because they are POST requests):

```javascript
const resp = await fetch('/api/linkedin/search', {
  method: 'POST',
  headers: { 'Accept': 'text/event-stream', 'Content-Type': 'application/json' },
  body: JSON.stringify({ name, company, title, location, email, max_profiles: 10 }),
  signal: controller.signal
});
// Read resp.body with ReadableStream, split on \n\n, parse lines starting with "data:"
```

### People lookup flow (frontend)

1. User submits `people-form`.
2. If already searching → `stopPeopleSearch()` (Search button toggles to Cancel).
3. `readPeopleForm()` extracts fields; detects profile URL in name/url inputs.
4. **Direct URL path:** `POST /api/linkedin` (sync, no SSE).
5. **Search path:** `streamPeopleSearch(...)`.
   - If response has `profiles` (server cache hit) → show profile cards directly.
   - Else show `candidates` filtered by `filterPeopleCandidates()` (strips banners, junk headlines).
   - If zero candidates but email/phone/company provided → `POST /api/people/enrich`.
6. User clicks **Look up** on a match → `scrapeLinkedInCandidates(onlyUrl)` via `/api/linkedin/stream`.
7. Scraped profiles merge with candidate visuals via `candidateVisualForUrl()` and `profileVisual()`.

### Visual rendering rules

| Context | Photo | Banner |
|---|---|---|
| Search match cards | Yes (from search thumbnail) | No (explicitly cleared in `filterPeopleCandidates`) |
| Scraped profile cards | Yes (fresh from LinkedIn) | Yes (from full scrape) |
| Cached profiles (re-search) | Re-scraped on demand | Re-scraped on demand |

`profileVisual(p)` prefers the profile's own `photo`/`banner`; if missing, falls back to the matching search candidate's photo.

### Lead investigation flow

1. `investigateLead(id)` — simulated progress steps every 6s while waiting.
2. `POST /api/lead/investigate` with `{ email, max_profiles: 2 }`.
3. On success, strips `result.company.news.articles` (news is separate).
4. 120s hard timeout calls `/api/lead/investigate/stop`.
5. `lookupLeadNews(id)` — `POST /api/company/news` with company name from parsed email.
6. `openLinkedInFromLead(id)` — prefills people tab and switches tab.

### Dashboard and bookmarks

- `dashboardCompanies()` merges `state.reports` with bookmarked lead companies.
- `toggleBookmark(key)` — optimistic UI update + `POST/DELETE /api/bookmarks`; triggers background refresh.
- `refreshBookmarkedCompanies()` — `POST /api/company/refresh`; polls `loadReports()` every 15s while background refresh runs.

---

## 5. Chrome extension (`extension/`)

The extension is a Chrome MV3 side panel that runs the same JavaScript logic as the web app, but as a remote UI shell pointing at the local Flask server.

| File | Role |
|---|---|
| `manifest.json` | MV3, `sidePanel` permission, host permissions for `127.0.0.1:5000` |
| `background.js` | Sets `chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true })` |
| `sidepanel.html` | 3-tab layout: Lead, Company, People (no Dashboard) |
| `js/app.js` | Fork of `front/js/app.js` with API base URL shim |
| `css/style.css`, `sidebar.css` | Styling adapted for narrow side panel |

### Differences from `front/`

| Aspect | Web app | Extension |
|---|---|---|
| Default tab | `dashboard` | `lead` |
| Dashboard | Full stats + company grid | Absent; `switchTab('dashboard')` redirects to `lead` |
| API URLs | Relative `/api/...` | `API_BASE = 'http://127.0.0.1:5000'` via patched `fetch` and `EventSource` |
| CSP | Flask-served | Extension CSP allows images from localhost + https |
| Requires | Flask running locally | Same — extension is not standalone |

Core logic (state management, SSE parsing, scrape/search flows, rendering) is otherwise identical.

---

## 6. Company intelligence pipeline (`web scraper/`)

The company pipeline turns a free-text query (company name or ticker) into a structured `CompanyDossier`. Entry point: `web scraper/src/pipeline.py` → `run_pipeline()`.

### Pipeline stages

```
query string
    │
    ▼
resolve_identity()          ← resolve.py — Finnhub/Yahoo/AV search, Wikipedia, SEC CIK
    │
    ▼
Parallel adapter fetches:
    ├── finnhub.py          ← profile, metrics, symbol search
    ├── yahoo.py            ← quote, summary profile
    ├── wikipedia.py        ← company description
    ├── sec_edgar.py        ← US filings (SEC EDGAR)
    ├── nse.py              ← India NSE announcements
    ├── alpha_vantage.py    ← overview/financials
    ├── github.py           ← org/repos
    ├── rss.py              ← company RSS feeds
    ├── newsapi.py          ← news discovery
    └── gnews.py            ← news discovery
    │
    ▼
filter_relevant_articles()  ← news_relevance.py — Groq or heuristics
enrich_articles()           ← news_enrich.py — Playwright opens article URLs
    │
    ▼
merge_dossier()             ← merge.py — combines all SourceResult into CompanyDossier
    │
    ▼
arrange_text()              ← arrange_text.py — Groq polishes description + highlights
    │
    ▼
CompanyDossier.validate()   ← schema.py — Pydantic validation
    │
    ▼
put_company(key, payload)   ← store.py — Supabase or local JSON
```

### Progress emission

`_emit(pct, step)` calls a module-level `_progress_callback` set by Flask before running the pipeline. Percentages map to stages:

| % | Stage |
|---|---|
| 5–15 | Identity resolution |
| 15–20 | Finnhub profile |
| 20–25 | Yahoo quote |
| 25–50 | Public records (Wikipedia, SEC/NSE, GitHub, RSS, Alpha Vantage) |
| 55–70 | News fetch + relevance filter + article enrichment |
| 80–95 | Merge + LLM arrange |
| 95–100 | Save to store |

### Pipeline modes

| Flag | Effect |
|---|---|
| `lite=True` | Skips GitHub, RSS, news fetch; preserves prior news if still fresh |
| `skip_news=True` | No news API calls |
| `use_groq=False` | Skips LLM description polish and news relevance filtering |
| `use_playwright=False` | Skips Playwright article body fetch |
| `fast` (from UI) | Maps to `use_groq=not fast`, `use_playwright=not fast` |

Bookmark background refresh uses `lite=True, skip_news=True, use_groq=False, use_playwright=False`.

### Identity resolution (`resolve.py`)

`resolve_identity()` is the first and most critical step. It:

1. Searches Finnhub for ticker symbols matching the query.
2. Falls back to Yahoo Finance search.
3. Checks Wikipedia for disambiguation (rejects pages titled "X may refer to").
4. Looks up SEC EDGAR CIK for US companies.
5. Returns a `ResolveContext` with `{ ticker, name, website, domain, exchanges, cik }`.

### Adapter modules

Each adapter in `web scraper/src/adapters/` returns a `SourceResult`:

```python
SourceResult(source="finnhub", ok=True, data={...})
SourceResult(source="yahoo", ok=False, error="symbol not found")
```

| Adapter | Data source | Env key |
|---|---|---|
| `yahoo.py` | Yahoo Finance quote/search | — |
| `finnhub.py` | Company profile, metrics | `FINNHUB_API_KEY` |
| `alpha_vantage.py` | Overview, financials | `ALPHA_VANTAGE_API_KEY` |
| `wikipedia.py` | Company description | — |
| `sec_edgar.py` | US SEC filings | `SEC_USER_AGENT` |
| `nse.py` | India NSE announcements | — |
| `newsapi.py` | News discovery | `NEWSAPI_API_KEY` |
| `gnews.py` | News discovery | `GNEWS_API_KEY` |
| `github.py` | Org/repos | `GITHUB_TOKEN` |
| `rss.py` | Company RSS feeds | — |

Adapters use `HttpClient` (shared async HTTP) and respect `RateLimits` for API throttling. Results are cached via `get_cached(source, key, ttl)` in `store.py`.

### Merge and schema

`merge.py` → `merge_dossier()` combines all `SourceResult` objects into a single `CompanyDossier` Pydantic model defined in `schema.py`:

- `Overview` — name, ticker, description, exchange, website, industry, employees
- `Financials` — revenue, profit, market cap, P/E, 52-week range
- `Filings` — SEC/NSE filing list
- `News` — articles with title, url, source, date, body
- `Press` — press releases
- `GitHub` — org link, repo count
- `Sources` — which adapters succeeded

`arrange_text.py` sends a condensed snapshot to Groq and receives polished `description` and `highlights` text.

### Local output paths

When Supabase is not configured, dossiers are written to:

| Path | Contents |
|---|---|
| `not to share/web scraper/output/company/{key}.json` | Full dossier |
| `not to share/web scraper/output/.cache/{source}/{key}.json` | Adapter HTTP cache |
| `not to share/web scraper/output/news/{key}/{date}.json` | Daily news buckets |
| `not to share/web scraper/people/{key}.json` | Person records |
| `not to share/web scraper/workspace.json` | UI workspace snapshot |
| `not to share/web scraper/bookmarks.json` | Bookmark keys |

`company_key(query)` produces a lowercase alphanumeric slug used as the primary key everywhere.

---

## 7. Lead finder (`lead finder/`)

The lead finder connects email parsing, company pipeline invocation, and LinkedIn people search.

### Email parsing (`src/email_parse.py`)

| Function | What it does |
|---|---|
| `classify_email(email)` | Returns `ParsedEmail` dataclass |
| `get_email_domain(email)` | Split on `@` |
| `is_corporate_email(domain)` | True if domain not in free provider list (`free_email_domains.py`) |
| `name_from_email(local_part)` | `satya.nadella` → `Satya Nadella` |
| `company_from_domain(domain)` | `microsoft.com` → `Microsoft` |

### Orchestration (`src/orchestrate.py`)

`run_lead_finder(email, ...)` is the main entry point:

```
classify_email(email)
    │
    ├─ corporate email?
    │   └─ run_company_pipeline(parsed.company)  → subprocess into web scraper
    │
    ├─ unless no_search:
    │   └─ search_people_urls(parsed.name, parsed.company)
    │
    └─ unless no_scrape:
        └─ run_linkedin_scrape(candidate_urls)  → via path_swap into lead scraper
```

**UI investigation mode** passes `no_scrape=True, no_search=True` — only the company dossier runs.

`run_company_pipeline()` spawns a subprocess running `asyncio.run(run_pipeline(...))` with a 60s (fast) or 300s timeout.

### LinkedIn people search (`src/linkedin_search.py`)

`search_people_urls(name, company, title, location, max_profiles, headless, on_progress)` is the search engine:

1. **Auth** — `create_authenticated_context()` from lead scraper (shared Playwright session).
2. **Navigate** — `_search_url()` builds LinkedIn global search URL with keywords + optional `titleFreeText` facet. Network filter set to `["F","S","O"]` (1st, 2nd, 3rd+ connections).
3. **Expand results** — `_open_people_show_all()` clicks "Show all people" or the People tab.
4. **Clear filters** — `_ensure_global_search()` removes connection-only filter chips.
5. **Extract** — Scrolls results and runs `_EXTRACT_JS` in the page context. This JavaScript:
   - Finds profile links inside search result cards only (not sidebar).
   - Extracts name, headline, location, photo URL per card.
   - Filters out junk: mutual connection text, degree badges, action buttons.
   - Caps at `max_profiles` (default 10).
6. **Photo capture** — `_capture_search_shots()` downloads or screenshots card photos as base64.
7. **Returns** — List of `{ url, name, headline, location, photo, banner, companies, key }`.

Progress is emitted via `_progress(on_progress, pct, step)` callback, serialized as JSON lines to subprocess stdout.

### Path swap (`src/path_swap.py`)

Both `lead finder` and `lead scraper` have a `src/` package. `linkedin_src_path()` is a context manager that temporarily removes `lead finder` from `sys.path`, inserts `lead scraper`, and clears cached `src.*` modules so imports resolve to the scraper's code.

---

## 8. LinkedIn profile scraper (`lead scraper/`)

The lead scraper performs authenticated Playwright visits to individual LinkedIn profile pages, extracts structured data, enriches contacts from public web sources, and persists results.

### Configuration (`src/config.py`)

Reads `not to share/.env`. Key paths:

- `STATE_PATH` = `not to share/linkedin/storage/linkedin_state.json` (Playwright cookie/storage state)
- Settings: `linkedin_email`, `linkedin_password`, visit delays, `headless`, `checkpoint_timeout_seconds`

### Authentication (`src/auth.py`)

| Function | Role |
|---|---|
| `open_playwright()` | Starts sync Playwright |
| `create_authenticated_context()` | Launches Chromium; reuses saved session if valid |
| `_perform_login()` | Navigates to login, auto-fills credentials, waits for checkpoint |
| `_session_still_valid()` | Probes `/feed/` to check login state |
| `_dismiss_overlays()` | Clicks cookie consent / alert buttons |

Requires `LINKEDIN_EMAIL` + `LINKEDIN_PASSWORD`. After successful login, storage state is saved to `linkedin_state.json` for reuse.

### Profile extraction (`src/extract.py`)

**`extract_profile(page, url)`** — full scrape of one profile:

1. Attach Voyager API response listener (captures LinkedIn internal JSON from network requests matching `VOYAGER_URL_MARKERS`).
2. `page.goto(url)` with domcontentloaded wait.
3. Detect authwall → return `{ error: "auth_required" }`.
4. `_merge_captured()` — parse captured Voyager JSON via `_parse_voyager_profile()` and `_parse_contact_payload()`.
5. If name/headline still missing → `_fetch_profile_via_page()` (direct Voyager API call from page context).
6. If email/links missing → `_fetch_contact_via_page()` (contact info overlay API).
7. If still missing → `_extract_dom_profile()` (DOM fallback: h1, headline, role, company, location).
8. `_extract_profile_images()` — photo and banner as base64 JPEG.
9. `_extract_dom_contact()` + `_collect_profile_links()` — scrape visible contact info and external links.

**Photo extraction** (`_extract_profile_images`):

- Runs `_IMAGE_URLS_JS` in page context — scoped to the profile top card area.
- `pickPhoto()` tries top-card-specific selectors first, then falls back to `profile-displayphoto` images positioned near the h1 name element (avoids sidebar/recommendation photos).
- `_url_to_data()` fetches the image URL via Playwright request context and converts to base64.
- `_photo_screenshot()` — element screenshot fallback if URL extraction fails.
- Banner uses similar logic with `_banner_clip_shot()` as final fallback.

**`extract_profile_visuals(page, url)`** — lightweight path for cache refresh:

- Navigates to profile, runs `_extract_profile_images()` only.
- Returns `{ photo, banner }` without touching Voyager data or contacts.

### Contact enrichment (`src/contacts.py`)

**`cached_profile(url)`** — looks up `store.find_person_by_url()`. Returns cached row via `person_to_profile()` if the person has a name. Photo and banner are explicitly set to `None` in the cached response (visuals are refreshed separately).

**`enrich_profile(row, hints)`** — post-scrape enrichment pipeline:

1. Apply hints (name, company, role, location, email, phone) to empty fields.
2. Merge saved person contacts from store.
3. Resolve company website via dossier lookup or `_probe_company_site()`.
4. `_scan_site()` — crawl `/contact`, `/about`, `/team` pages for emails and phones.
5. Scan profile link URLs and GitHub profiles (`GITHUB_TOKEN`).
6. Build structured contact entries:
   - `email_entries` — `{ value, source }` where source is `linkedin`, `company_site`, `entered`, `github`, etc.
   - `phone_entries`, `company_email_entries`, `company_phone_entries`
7. `_persist()` → `store.upsert_person()` — saves metadata and contacts; **photo and banner are stripped before storage**.

### Scraper orchestration (`src/scraper.py`)

**`run(settings, on_progress, urls, hints)`**:

```
for each url:
  cached = cached_profile(url)
  if cached:
    → extract_profile_visuals(page, url)     # photo/banner only
    → merge visuals into cached row
    → emit progress with cached metadata
  else:
    → extract_profile(page, url)             # full scrape
    → enrich_profile(row, hints)             # contact enrichment + persist
    → emit progress with full profile
  random delay between visits
```

Emits JSON lines: `{ pct, step, index, total, profile? }`. The final line is the complete profile list array.

CLI entry: `lead scraper/main.py` — calls `run()` or `--view` for saved results.

---

## 9. Persistence layer (`web scraper/src/store.py`)

All data persistence goes through `store.py`. It tries Supabase first; on missing credentials or errors, falls back to local JSON files under `not to share/web scraper/`.

### Supabase client

```python
def _sb():
    # lazy-init from SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY

def using_db():
    # True if Supabase client initialized
```

### Companies

| Function | Behavior |
|---|---|
| `put_company(key, dossier)` | Upsert to `companies` table + optional local JSON |
| `get_company_record(key)` | Load + expire stale news + ensure summary fields |
| `find_company_record(query)` | Direct key lookup or fuzzy match on query/ticker/name |
| `list_companies()` | All dossiers ordered by `updated_at` |

News TTL: **24 hours** — stale news is stripped from dossiers and old `news_days` rows are purged.

### People

| Function | Behavior |
|---|---|
| `person_key(url, name, company)` | LinkedIn URL slug or name+company hash |
| `upsert_person(record)` | Merge contact entries; strip photo/banner from stored profile |
| `find_person_by_url(url)` | Slug match across DB + local files |
| `find_people_for_query(...)` | Token match on name, email, company, role, location |
| `person_to_profile(row)` | API-facing shape with `from_cache: true`; photo/banner set to `None` |
| `list_people()` | All person records from DB + local files merged |
| `_is_scraped_person(row)` | True if row has a name (valid cached person) |

**People matching logic** (`find_people_for_query`):

- If URL provided → direct slug lookup.
- Otherwise requires at least 2 name tokens OR an email OR a company.
- Matches stored records where name tokens overlap, email matches, company/role/location fuzzy-match.
- Only returns records that pass `_is_scraped_person()`.

**Photo/banner policy:** Metadata (name, headline, role, company, contacts) is stored permanently. Photo and banner are never saved to the database. When a cached person is displayed, visuals are re-scraped from LinkedIn on demand via `extract_profile_visuals()`.

### Workspace and bookmarks

| Function | Behavior |
|---|---|
| `get_workspace()` | Bookmarks from `bookmarks` table; leads with news expiry applied |
| `put_workspace(bookmarks, leads, linkedin)` | Upsert workspace row; sync bookmarks |
| `list_bookmarks()` / `add_bookmark()` / `remove_bookmark()` | Dedicated `bookmarks` table |
| `_migrate_workspace_bookmarks()` | One-time migration from legacy workspace JSON |

### Source cache

| Function | Behavior |
|---|---|
| `get_cached(source, key, ttl_seconds)` | Supabase `source_cache` or local `CACHE/{source}/{key}.json` |
| `set_cached(source, key, data)` | Upsert with `fetched_at` timestamp |
| `load_news_day(ckey, day)` / `save_news_day()` | Daily news buckets in `news_days` table or local files |

---

## 10. Database schema (`supabase/schema.sql`)

Six tables, all with RLS enabled and permissive policies (service-role access from Flask):

| Table | Primary key | Purpose |
|---|---|---|
| `companies` | `key` (text) | Full company dossier JSON in `dossier` jsonb column |
| `workspace` | `id` (always 1) | UI state: bookmarks array, leads array, linkedin form snapshot |
| `source_cache` | `(source, cache_key)` | Adapter HTTP response cache with `fetched_at` |
| `news_days` | `(company_key, day)` | Daily news article buckets |
| `bookmarks` | `company_key` | Pinned company keys with `created_at` |
| `people` | `key` | Scraped person records: name, company, email, phone, contact arrays, profile jsonb |

**People table detail:**

```
people
├── key              — person_key(url, name, company)
├── linkedin_url     — canonical profile URL
├── name             — display name
├── company          — current company
├── email            — primary email
├── phone            — primary phone
├── emails           — jsonb array of all emails
├── phones           — jsonb array of all phones
├── sources          — jsonb array of contact source tags
├── profile          — jsonb full profile (no photo/banner stored here)
└── updated_at       — last scrape timestamp
```

Apply the schema once in the Supabase SQL editor before first run.

---

## 11. People lookup — full decision tree

This is the most complex flow in the system. It spans search, cache, scrape, and visual refresh.

### Server-side (`POST /api/linkedin/search`)

```
Request: { name, company, title, location, email, phone, url, max_profiles }
    │
    ▼
find_people_for_query(name, company, email, title, location)
    │
    ├─ MATCH FOUND (stored person exists)
    │   │
    │   ├─ No LinkedIn URLs in stored records
    │   │   └─ SSE: instant return { cached: true, profiles: stored, candidates: [] }
    │   │
    │   └─ Has LinkedIn URLs
    │       └─ SSE: spawn _LI_RUNNER subprocess
    │           → scraper.run() with cached_profile() hits
    │           → extract_profile_visuals() for each URL (photo/banner only)
    │           → merge visuals into stored profiles
    │           → SSE: { cached: true, profiles: merged, candidates: [] }
    │
    └─ NO MATCH
        └─ SSE: spawn _LI_SEARCH subprocess
            → search_people_urls(name, company, ...)
            → stream progress events
            → SSE: { done: true, candidates: [...], profiles: [] }
```

### User clicks "Look up" on a search match

```
POST /api/linkedin/stream { urls: [profile_url], hints: { name, company, ... } }
    │
    ▼
scraper.run(urls, hints)
    │
    ├─ cached_profile(url) exists?
    │   └─ extract_profile_visuals() → merge photo/banner into cached row
    │
    └─ not cached
        └─ extract_profile() → enrich_profile() → upsert_person()
    │
    ▼
SSE: stream { pct, step, profile } events → final { done: true, profiles: [...] }
```

### Direct profile URL entered

```
POST /api/linkedin { url: "https://linkedin.com/in/..." }
    │
    ▼
Same as scrape above, but synchronous (no SSE), up to 5 URLs
```

### Contact-only enrichment (no LinkedIn)

```
POST /api/people/enrich { hints: { name, company, email, phone, ... } }
    │
    ▼
enrich_profile(stub_row, hints) — no Playwright
    → company website scan, GitHub lookup
    → upsert_person()
    │
    ▼
Returns enriched profile JSON
```

Used when search returns zero candidates but the user provided enough hints (email, phone, company) to attempt public contact discovery.

---

## 12. Environment variables and secrets

All secrets live in `not to share/.env` (gitignored). Loaded by Flask, pipeline, and lead scraper config.

| Variable | Used in | Purpose |
|---|---|---|
| `FINNHUB_API_KEY` | `adapters/finnhub.py` | Symbol search + company profile |
| `ALPHA_VANTAGE_API_KEY` | `adapters/alpha_vantage.py` | Overview/financials |
| `AV_DAILY_SOFT_CAP` | `alpha_vantage.py` | Default 20; tracks usage in `av_day.json` |
| `SEC_USER_AGENT` | `sec_edgar.py`, `resolve.py` | EDGAR API identity (`AppName you@email.com`) |
| `NEWSAPI_API_KEY` | `adapters/newsapi.py` | News discovery |
| `GNEWS_API_KEY` | `adapters/gnews.py` | News discovery |
| `NEWS_LOOKBACK_DAYS` | `pipeline.py` | Default 3 |
| `NEWS_ENRICH_TOP_N` | `news_enrich.py` | Default 8 articles to open with Playwright |
| `GROQ_API_KEY` | `arrange_text.py`, `news_relevance.py` | LLM calls via Groq OpenAI-compatible API |
| `GROQ_MODEL` | `arrange_text.py` | Default `llama-3.3-70b-versatile` |
| `NEWS_GROQ_MODEL` | `news_relevance.py` | Falls back to `GROQ_MODEL` |
| `GROQ_ARRANGE_MAX_CHARS` | `arrange_text.py` | Default 60000 |
| `GITHUB_TOKEN` | `adapters/github.py`, `contacts.py` | GitHub org/email lookup |
| `LINKEDIN_EMAIL` | `lead scraper/config.py` | Playwright login |
| `LINKEDIN_PASSWORD` | `lead scraper/config.py` | Playwright login |
| `SUPABASE_URL` | `store.py` | Postgres backend |
| `SUPABASE_SERVICE_ROLE_KEY` | `store.py` | Server-side DB access |
| `HEADLESS` | Set by Flask subprocesses | `"true"` → faster Playwright timeouts |

**Runtime paths (not env vars):**

| Path | Contents |
|---|---|
| `not to share/.venv/` | Python virtual environment |
| `not to share/linkedin/storage/linkedin_state.json` | Playwright session cookies |
| `not to share/web scraper/output/` | Local JSON fallback for all data |
| `not to share/web scraper/people/` | Local person records |

---

## 13. Design patterns used throughout

### SSE progress streaming

Long-running operations (company pipeline, LinkedIn search, profile scrape) stream progress to the frontend via Server-Sent Events instead of blocking HTTP responses.

- **Company:** Background thread + `queue.Queue` + pipeline callback.
- **LinkedIn:** Subprocess stdout with line-buffered JSON (`PYTHONUNBUFFERED=1`); Flask generator translates to SSE `data:` frames.
- **Client:** Native `EventSource` for GET streams; manual `fetch` + `ReadableStream` reader for POST streams.
- **Retry header:** LinkedIn streams emit `retry: 3600000` (1 hour) to prevent aggressive reconnection.

### Subprocess isolation

Flask never imports Playwright for LinkedIn. Each operation spawns a fresh Python subprocess with an inline `-c` script and explicit `sys.path.insert`. Benefits:

- Flask event loop stays responsive.
- Cancel kills the entire process tree (including Chromium).
- No sync/async mixing between Flask and Playwright.

### Supabase with local JSON fallback

Every write in `store.py` follows the same pattern:

```python
if using_db():
    try:
        supabase_upsert(...)
        return
    except Exception:
        pass
write_local_json(...)
```

This means the app works without Supabase configured — all data lands in `not to share/web scraper/`. When Supabase is added later, new writes go to the database while local files remain as backup.

### Cache layering

| Layer | TTL | What it caches |
|---|---|---|
| Company dossier freshness | 6 hours | Stream shortcut — skip pipeline if dossier is recent and complete |
| News day bucket | 24 hours | Daily news articles per company |
| Source cache | Per-adapter TTL | Raw HTTP responses from Finnhub, AV, etc. |
| People metadata | Permanent | Name, headline, role, company, contacts |
| People visuals | On demand | Photo/banner re-scraped from LinkedIn each time |
| Bookmark refresh | 24 hours | Triggers lite pipeline for stale bookmarked companies |

### Contact provenance

Every email and phone is stored as `{ value, source }`:

| Source tag | Meaning |
|---|---|
| `linkedin` | From LinkedIn profile or contact overlay |
| `company_site` | Found on company website `/contact`, `/about` |
| `entered` | User provided in the search form |
| `github` | From GitHub profile |
| `profile_link` | From a link on the LinkedIn profile |
| `saved` | From a previous scrape in the database |

Generic company emails (`info@`, `contact@`, `support@`) are routed to `company_email_entries`, not personal email fields.

### Playwright session reuse

A single `linkedin_state.json` file stores cookies and local storage from the last successful login. Both people search and profile scrape reuse this session. If the session expires, the auth module re-logs in using `LINKEDIN_EMAIL`/`LINKEDIN_PASSWORD` and saves the new state.

Headless mode tightens timeouts: `checkpoint_timeout_seconds` capped at 20s, visit delays reduced to 0.6–1.2s.

### News handling differences

| Context | News behavior |
|---|---|
| Company Search tab | Full news included in pipeline |
| Lead investigation | News stripped on frontend; user triggers separately |
| Bookmark background refresh | Preserves existing news if still fresh (`lite=True`) |
| Lead "Look up news" button | `POST /api/company/news` fetches news on demand |

### Frontend cancel pattern

Every long-running operation supports cancellation:

1. Search/Investigate/Scrape buttons toggle to "Cancel" / "Stop" while active.
2. Frontend aborts the fetch via `AbortController`.
3. Frontend calls the corresponding `/stop` endpoint.
4. Flask kills the subprocess under the appropriate lock.
5. Partial results already received are preserved in state.

---

## Quick reference: file map

```
.
├── ui/app.py                          Flask orchestrator (all API endpoints)
├── front/
│   ├── index.html                     SPA shell (4 tabs)
│   ├── js/app.js                      All frontend logic
│   └── css/style.css                  Dark-mode styling
├── extension/
│   ├── manifest.json                  Chrome MV3 side panel config
│   ├── sidepanel.html                 3-tab extension UI
│   ├── js/app.js                      Same logic, API base URL patched
│   └── background.js                  Side panel opener
├── web scraper/
│   └── src/
│       ├── pipeline.py                Company dossier pipeline
│       ├── resolve.py                 Identity resolution
│       ├── merge.py                   Dossier assembly
│       ├── schema.py                  Pydantic models
│       ├── store.py                   Supabase + local persistence
│       ├── arrange_text.py            Groq LLM polish
│       ├── news_relevance.py          News filtering
│       ├── news_enrich.py             Article body fetch
│       └── adapters/                  Yahoo, Finnhub, SEC, news, etc.
├── lead finder/
│   └── src/
│       ├── orchestrate.py             Email → company + search orchestration
│       ├── email_parse.py             Email classification
│       ├── linkedin_search.py         Playwright people search
│       └── path_swap.py               sys.path context manager
├── lead scraper/
│   └── src/
│       ├── scraper.py                   Profile scrape orchestration
│       ├── extract.py                   Voyager + DOM + image extraction
│       ├── contacts.py                  Contact enrichment + persistence
│       ├── auth.py                        Playwright login/session
│       └── config.py                      Settings + paths
├── supabase/schema.sql                Database tables
└── not to share/                      Secrets, venv, sessions, local data
```
