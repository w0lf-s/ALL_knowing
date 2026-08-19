# How to run

Project root (this folder):

`ALL Knowing`

All commands below assume you are in that folder (PowerShell).

Private files (keys, venv, outputs, caches, LinkedIn session) live under `not to share\` and must not be committed.

For a deep dive into how each component works, see [`explanation.md`](explanation.md).

---

## 1. One-time setup

### Requirements

- Python 3.11 or newer
- Internet access (API calls + Playwright)
- [Supabase](https://supabase.com) project (recommended — local JSON fallback works without it)
- Playwright Chromium (LinkedIn + news article bodies)

### Shared virtualenv

```powershell
python -m venv "not to share\.venv"
.\not to share\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium
```

Later sessions:

```powershell
.\not to share\.venv\Scripts\Activate.ps1
```

### Create `not to share\.env`

There is only one env file: `not to share\.env`. Do not add `.env` files in `web scraper`, `lead scraper`, `lead finder`, `ui`, or `front`.

Create the file manually and fill in keys:

```env
FINNHUB_API_KEY=
ALPHA_VANTAGE_API_KEY=
SEC_USER_AGENT=
NEWSAPI_API_KEY=
GNEWS_API_KEY=
GROQ_API_KEY=
GROQ_MODEL=
NEWS_GROQ_MODEL=
GITHUB_TOKEN=
LINKEDIN_EMAIL=
LINKEDIN_PASSWORD=
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
```

| Variable | Required? | Used for |
|----------|-----------|----------|
| `FINNHUB_API_KEY` | Yes (ticker/profile) | Resolve + profile/metrics |
| `ALPHA_VANTAGE_API_KEY` | Yes (OVERVIEW) | Financials |
| `SEC_USER_AGENT` | Yes | SEC EDGAR (must look like `AppName you@email.com`) |
| `NEWSAPI_API_KEY` | Recommended | News discovery |
| `GNEWS_API_KEY` | Recommended | News discovery |
| `GROQ_API_KEY` | Recommended | News relevance + overview/highlights |
| `GROQ_MODEL` | Optional | Overview/highlights model |
| `NEWS_GROQ_MODEL` | Optional | Faster model for news relevance |
| `GITHUB_TOKEN` | Optional | GitHub org/repos (skipped if empty) |
| `LINKEDIN_EMAIL` | Yes for People Lookup | Playwright login for search + scrape |
| `LINKEDIN_PASSWORD` | Yes for People Lookup | Playwright login for search + scrape |
| `SUPABASE_URL` | Recommended | Dossiers, people, bookmarks, workspace |
| `SUPABASE_SERVICE_ROLE_KEY` | Recommended | Server-side DB access from Flask |

Optional knobs:

- `NEWS_LOOKBACK_DAYS=3`
- `NEWS_ENRICH_TOP_N=8`
- `AV_DAILY_SOFT_CAP=20`
- `GROQ_ARRANGE_MAX_CHARS=60000`

### Supabase (recommended)

1. Create a Supabase project.
2. Open the SQL editor and run [`supabase/schema.sql`](supabase/schema.sql) once.
3. Add `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` to `not to share\.env`.

Tables created: `companies`, `source_cache`, `news_days`, `workspace`, `bookmarks`, `people`.

Without Supabase, everything falls back to JSON files under `not to share\web scraper\`.

Without Playwright Chromium, company/news search still runs, but article bodies stay empty and People Lookup will not work.

---

## 2. Run the UI (normal way)

Keep the venv activated, then:

```powershell
python ui\app.py
```

Open:

http://127.0.0.1:5000

Tabs:

| Tab | What it does |
|-----|----------------|
| **Dashboard** | Browse tracked companies, search, bookmark, open dossier cards |
| **Lead** | Add an email → **Investigate** (company dossier only). News is **not** fetched during investigate. After **View**, use **Look up news** to fetch articles on demand |
| **Company Search** | Full company pipeline (identity, financials, filings, **news included**) |
| **People Lookup** | Search by name, company, role, location, email, phone, or profile URL → review matches → **Look up** one or all profiles |

People Lookup notes:

- **Search** finds LinkedIn matches (up to 10). Match cards show photo only — no banner.
- **Look up** scrapes the full profile (headline, role, company, contacts, banner).
- If the person was scraped before, metadata loads from the database; photo and banner are refreshed from LinkedIn.
- **Search** toggles to **Cancel** while a search is running. **Stop** cancels an active scrape.

Lead notes:

- **Stop** cancels a running investigation. Starting another investigation stops the previous one.

Ctrl+C in the terminal stops the Flask server.

---

## 3. Run the Chrome extension (optional)

The extension is a side-panel UI that talks to the same Flask server. It does not include the Dashboard tab.

1. Start Flask first (`python ui\app.py`).
2. Open Chrome → **Extensions** → **Manage extensions** → enable **Developer mode**.
3. **Load unpacked** → select the `extension\` folder.
4. Click the extension icon to open the side panel.

The extension calls `http://127.0.0.1:5000` for all API requests. Flask must be running locally.

Tabs in the extension: **Lead**, **Company**, **People** (same behavior as the web app).

---

## 4. Run pieces from the CLI (optional)

Use these when you do not want the UI. Always activate the venv first.

### A. Company scraper (full JSON)

```powershell
cd "web scraper"
python -m src "Apple"
python view_lastrun.py
cd ..
```

Replace `"Apple"` with any company name.

Flags:

```powershell
cd "web scraper"
python -m src "Apple" --summary
python -m src "Apple" --no-groq
python -m src "Apple" --no-playwright
python -m src "Apple" --no-groq --no-playwright
python -m src --help
python view_lastrun.py --help
python view_lastrun.py --path "..\not to share\web scraper\lastrun.json"
cd ..
```

`--no-playwright` = titles/summaries only (no article body scrape).

### B. Lead finder

```powershell
cd "lead finder"
python main.py --list-samples
python main.py "satya.nadella@microsoft.com"
python main.py --cookie "..\not to share\lead finder\cookies\satya-nadella-microsoft.json"
python main.py "satya.nadella@microsoft.com" --no-scrape
python main.py "satya.nadella@microsoft.com" --no-search
python main.py "satya.nadella@microsoft.com" --headed
cd ..
```

CLI lead finder runs the **live** pipeline (includes company news + LinkedIn search + scrape). The UI Lead tab uses a faster investigate path (`--no-scrape --no-search`) and skips news until **Look up news** is pressed.

### C. LinkedIn profile scraper

```powershell
cd "lead scraper"
python main.py
python main.py --view
cd ..
```

Put profile URLs in `not to share\linkedin\urls.txt` (one per line). A Chromium window opens by default; complete any checkpoint/2FA there. Session is saved to `not to share\linkedin\storage\linkedin_state.json`.

---

## 5. Outputs (where to look)

Run data is under `not to share\` (and Supabase if configured).

| Path | Purpose |
|------|---------|
| `not to share\web scraper\lastrun.json` | Latest successful company dossier (CLI) |
| `not to share\web scraper\output\company\{key}.json` | Per-company dossier (local fallback) |
| `not to share\web scraper\output\raw\{key}.json` | Raw API payloads |
| `not to share\web scraper\output\news\{key}\{YYYY-MM-DD}.json` | Same-day news cache |
| `not to share\web scraper\output\.cache\...` | TTL caches (Finnhub, Yahoo, Alpha Vantage, SEC, Wikipedia, NSE, RSS, GitHub) |
| `not to share\web scraper\people\{key}.json` | Scraped person records (local fallback) |
| `not to share\web scraper\workspace.json` | UI workspace snapshot (local fallback) |
| `not to share\web scraper\bookmarks.json` | Bookmark keys (local fallback) |
| `not to share\lead finder\output\` | Lead last-run + candidate URLs |
| `not to share\linkedin\output\` | LinkedIn scrape results (CLI) |
| `not to share\linkedin\storage\` | LinkedIn session (`linkedin_state.json`) |

With Supabase configured, dossiers, people, bookmarks, and workspace are also stored in Postgres. Flask is the only client — the browser never talks to Supabase directly.

`{key}` is a slug of the query (example: `Apple` → `apple`, `Alphabet Inc` → `alphabet-inc`).

The browser keeps UI state in **sessionStorage** (`zuntraFrontUi`) until the tab is closed. Bookmarks and leads sync to Supabase via `PUT /api/workspace`.

---

## 6. Caching behavior

- **Company Search (UI):** if a dossier is newer than **6 hours** and has a plausible ticker + financials, the pipeline is skipped.
- **Same company, same day news:** if today's news bucket exists, NewsAPI/GNews are skipped. Playwright still runs if cached articles have empty `content`.
- **Alpha Vantage:** OVERVIEW cached ~7 days per ticker; daily soft-cap limits fresh calls.
- **Yahoo / Finnhub / Wikipedia / SEC / NSE / RSS / GitHub:** TTL files under `output\.cache\` (or `source_cache` in Supabase).
- **Lead investigate (UI):** does not search news or LinkedIn. **Look up news** fetches news only when pressed.
- **People Lookup:** profile metadata (name, headline, role, company, contacts) is cached permanently in the `people` table. Photo and banner are **not** stored — they are re-scraped from LinkedIn when needed.
- **Bookmarked companies:** background refresh runs if dossier is older than **24 hours**.
- **Failed run:** does not overwrite a previous good `lastrun.json`.
- **Playwright launch failure:** search continues without article bodies.

Stale or wrong data (typos like `nvdia`, empty financials, old news) is almost always a cache hit. Clear cache, then search again.

---

## 7. How to clear cache

Paths are relative to the **project root** (`ALL Knowing`).

### A. Clear company/news API caches (usual fix)

TTL cache + same-day news:

```powershell
Remove-Item -Recurse -Force ".\not to share\web scraper\output\.cache" -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force ".\not to share\web scraper\output\news" -ErrorAction SilentlyContinue
```

### B. Also wipe saved company dossiers + last run

Needed if Company Search keeps loading an old dossier (the 6-hour UI cache):

```powershell
Remove-Item -Recurse -Force ".\not to share\web scraper\output\raw" -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force ".\not to share\web scraper\output\company" -ErrorAction SilentlyContinue
Remove-Item -Force ".\not to share\web scraper\lastrun.json" -ErrorAction SilentlyContinue
```

### C. Wipe all web-scraper output

```powershell
Remove-Item -Recurse -Force ".\not to share\web scraper\output" -ErrorAction SilentlyContinue
Remove-Item -Force ".\not to share\web scraper\lastrun.json" -ErrorAction SilentlyContinue
```

### D. Clear only one company's news for today

```powershell
Remove-Item -Force ".\not to share\web scraper\output\news\apple\2026-08-19.json" -ErrorAction SilentlyContinue
```

Use the real slug folder and date filename on your machine.

### E. Clear lead / LinkedIn / people run files

```powershell
Remove-Item -Recurse -Force ".\not to share\lead finder\output" -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force ".\not to share\linkedin\output" -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force ".\not to share\web scraper\people" -ErrorAction SilentlyContinue
```

Do **not** delete `not to share\linkedin\storage\` unless you want to force a fresh LinkedIn login.

To clear people from Supabase, delete rows from the `people` table in the Supabase dashboard.

### F. Clear the UI tab state (browser)

Lead list / last company result / People panel state is stored in the browser tab, not on disk.

- Close the tab, or
- DevTools → Application → Session Storage → `http://127.0.0.1:5000` → delete `zuntraFrontUi`, then refresh.

After clearing disk cache, run the search again (no need to restart Flask unless it is not running).

---

## 8. Quick recipes

### UI from a clean cache

```powershell
.\not to share\.venv\Scripts\Activate.ps1
Remove-Item -Recurse -Force ".\not to share\web scraper\output\.cache", ".\not to share\web scraper\output\news", ".\not to share\web scraper\output\company" -ErrorAction SilentlyContinue
python ui\app.py
```

Then open http://127.0.0.1:5000

### Company CLI + view (fresh)

```powershell
.\not to share\.venv\Scripts\Activate.ps1
Remove-Item -Recurse -Force ".\not to share\web scraper\output\.cache", ".\not to share\web scraper\output\news" -ErrorAction SilentlyContinue
cd "web scraper"
python -m src "Apple"
python view_lastrun.py
cd ..
```

### Fast dry run (no LLM, no browser)

```powershell
cd "web scraper"
python -m src "Microsoft" --no-groq --no-playwright --summary
python view_lastrun.py
cd ..
```

### People Lookup from CLI (full pipeline)

```powershell
cd "lead finder"
python main.py "name@company.com" --headed
cd ..
```

Runs company pipeline + LinkedIn search + profile scrape in one command.

---

## 9. Common issues

| Problem | What to do |
|---------|------------|
| `Activate.ps1` cannot be loaded | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| UI opens but searches fail | Confirm `not to share\.env` has keys; confirm venv is activated |
| Company Search instantly "Complete" with old/wrong data | Clear `output\company` and `output\.cache` (6-hour dossier cache) |
| News missing or stale | Clear `output\news` and `output\.cache`; on Lead tab press **Look up news** |
| `Missing file: ...\lastrun.json` | Run a company search first (UI or `python -m src "Company"`) |
| Playwright / `Executable doesn't exist` | `python -m playwright install chromium` |
| News titles but no body text | Install Chromium; do not use `--no-playwright`; clear `output\news` |
| GitHub always fails | Set `GITHUB_TOKEN` or ignore (optional) |
| Alpha Vantage empty / rate limited | Wait, or clear `.cache\alpha_vantage` only if you need a fresh OVERVIEW |
| LinkedIn checkpoint / login loop | Run headed (`--headed`), complete 2FA; or delete `not to share\linkedin\storage` and log in again |
| People Lookup returns wrong/no photo | LinkedIn DOM may have changed; keep volume low; try a fresh login |
| People Lookup shows cached data instantly | Expected — metadata is stored; photo/banner refresh in background |
| Lead investigation stuck | Press **Stop**, then Investigate again |
| Extension shows connection errors | Flask must be running on `127.0.0.1:5000` |
| Supabase data not appearing | Confirm schema was applied and service role key is set |
| Want to avoid browser / Groq (CLI only) | `--no-playwright` / `--no-groq` |

---

## 10. Command cheat sheet

```powershell
.\not to share\.venv\Scripts\Activate.ps1
python ui\app.py

cd "web scraper"
python -m src "Company Name"
python -m src "Company Name" --summary
python -m src "Company Name" --no-groq
python -m src "Company Name" --no-playwright
python view_lastrun.py
cd ..

cd "lead finder"
python main.py --list-samples
python main.py "name@company.com"
python main.py "name@company.com" --no-scrape
python main.py "name@company.com" --headed
cd ..

cd "lead scraper"
python main.py
python main.py --view
cd ..

python -m playwright install chromium

Remove-Item -Recurse -Force ".\not to share\web scraper\output\.cache", ".\not to share\web scraper\output\news", ".\not to share\web scraper\output\company" -ErrorAction SilentlyContinue
```
