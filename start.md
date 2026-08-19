# Agent Start Guide — Zuntra Lead Intelligence

You are taking over this repository. Read this file first, then follow the steps in order.

---

## Mission

This is a **local-first lead intelligence app**. It turns a company name, email, or person search into structured dossiers (financials, news, LinkedIn profiles, contacts). A Flask server on port 5000 orchestrates everything. The browser never talks to Supabase directly.

Your job when working here: understand the architecture before editing, run the app to verify behavior, and never commit secrets.

---

## Read these files (in order)

| Order | File | Why |
|---|---|---|
| 1 | `start.md` (this file) | Boot sequence and rules |
| 2 | `README.md` | Product overview and feature list |
| 3 | `HOW_TO_RUN.md` | Setup, run commands, cache clearing, troubleshooting |
| 4 | `explanation.md` | Deep architecture — read before touching backend logic |
| 5 | `supabase/schema.sql` | Database tables if working on persistence |
| 6 | `ui/app.py` | All API endpoints and subprocess orchestration |
| 7 | `front/js/app.js` | Frontend state, SSE, UI flows |
| 8 | `web scraper/src/store.py` | Single persistence layer (Supabase + fallback) |
| 9 | `web scraper/src/pipeline.py` | Company dossier pipeline |
| 10 | `lead finder/src/linkedin_search.py` | LinkedIn people search |
| 11 | `lead scraper/src/scraper.py` + `extract.py` | Profile scrape and image extraction |

---

## Architecture (30-second version)

```
Browser (front/ or extension/)
    → Flask (ui/app.py :5000)
        → web scraper/     company dossiers
        → lead finder/     email parse + LinkedIn search
        → lead scraper/    LinkedIn profile scrape + contacts
        → store.py         Supabase (primary) or local JSON (fallback)
```

**Critical rules:**
- Browser → Flask only. Flask → Supabase only.
- LinkedIn runs in **subprocesses**, not inside Flask directly.
- People metadata is stored in Supabase; photo/banner are re-scraped on demand (not stored in DB).
- Secrets live in `not to share/.env` — never commit this folder.

---

## First-run setup

Project root is the folder containing `ui/`, `front/`, `README.md`.

### 1. Check prerequisites

- Python 3.11+
- Internet access
- Supabase project (recommended — app works without it but uses local JSON fallback)
- API keys (see env list below)

### 2. Create virtualenv and install

```powershell
python -m venv "not to share\.venv"
.\not to share\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium
```

On Linux/macOS, venv path is `not to share/.venv/bin/activate`.

### 3. Create environment file

Create `not to share/.env` (this file is gitignored):

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

If `.env` is missing, the app may start but searches will fail. Ask the user for keys — do not invent them.

### 4. Set up Supabase

1. Create a Supabase project.
2. Run `supabase/schema.sql` in the SQL editor once.
3. Put `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` in `.env`.

Tables: `companies`, `source_cache`, `news_days`, `workspace`, `bookmarks`, `people`.

When Supabase is configured, dossiers and people go to the database — not local JSON files.

### 5. Start the server

```powershell
.\not to share\.venv\Scripts\Activate.ps1
python ui\app.py
```

Open: http://127.0.0.1:5000

Ctrl+C stops the server.

### 6. Verify it works

Run these checks after starting:

| Check | How |
|---|---|
| Server up | http://127.0.0.1:5000 loads the dashboard |
| Supabase connected | Run company search; check `companies` table in Supabase dashboard |
| People lookup | Search a name + company on People tab; complete LinkedIn login if prompted |
| Extension (optional) | Load `extension/` unpacked in Chrome; requires Flask running |

Quick Supabase connectivity test:

```powershell
& ".\not to share\.venv\Scripts\python.exe" -c "import sys; from pathlib import Path; from dotenv import load_dotenv; load_dotenv(Path('not to share')/'.env'); sys.path.insert(0,'web scraper'); from src.store import using_db; print('using_db:', using_db())"
```

Expected output: `using_db: True`

---

## What is NOT in GitHub

The `not to share/` folder is gitignored. A fresh clone will not have:

| Missing | Action |
|---|---|
| `.env` | User must create with their own API keys |
| `.venv/` | Agent runs setup commands above |
| Supabase data | User creates own project + runs schema |
| `linkedin_state.json` | Created on first LinkedIn login via Playwright |
| Sample cookie files | Optional demo data for Lead tab |

Do not ask the user to commit anything under `not to share/`.

---

## Key entry points by task

| Task | Start here |
|---|---|
| Fix UI / tabs / SSE | `front/js/app.js`, `front/css/style.css` |
| Fix Chrome extension | `extension/js/app.js` (fork of front with API base URL patch) |
| Fix API endpoint | `ui/app.py` |
| Fix company search / dossier | `web scraper/src/pipeline.py`, `merge.py`, `adapters/` |
| Fix people search | `lead finder/src/linkedin_search.py` |
| Fix profile scrape / photos | `lead scraper/src/extract.py`, `scraper.py` |
| Fix contact enrichment | `lead scraper/src/contacts.py` |
| Fix DB read/write | `web scraper/src/store.py` |
| Fix schema | `supabase/schema.sql` |

---

## Main user flows (know these before debugging)

### Company Search
User enters company name → `GET /api/company/stream` → `run_pipeline()` → dossier saved via `put_company()` → displayed on Company tab.

### Lead Investigation
User enters email → `POST /api/lead/investigate` → company pipeline only (no news, no LinkedIn). News fetched separately via **Look up news**.

### People Lookup
1. User searches name/company → `POST /api/linkedin/search` (SSE)
2. If person exists in DB → return cached metadata, refresh photo/banner
3. If not → Playwright search → show match cards
4. User clicks **Look up** → `POST /api/linkedin/stream` → full scrape → `upsert_person()`

Search match cards show photo only. Scraped profile cards show photo + banner.

---

## Persistence rules (current behavior)

When `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` are set:

- Companies, people, bookmarks, workspace, source cache, news days → **Supabase**
- Local JSON under `not to share/web scraper/` is **fallback only** when Supabase is not configured
- `av_day.json` (Alpha Vantage rate limit) is always local — this is intentional
- `linkedin_state.json` (Playwright session) is always local — this is intentional

---

## Agent constraints

When editing this codebase:

1. **Never commit** `not to share/`, `.env`, or API keys.
2. **Never add** console.log, print, or debug output unless the user explicitly asks.
3. **Never add** code comments unless the user explicitly asks.
4. **Do not run production builds** unless the user explicitly asks.
5. **Flask must be restarted** after Python backend changes.
6. **LinkedIn automation is fragile** — keep volume low; DOM selectors break when LinkedIn changes layout.
7. **Front and extension** share logic — if you edit `front/js/app.js`, check if `extension/js/app.js` needs the same change.
8. **Only commit when asked** — do not create git commits proactively.

---

## Common issues

| Symptom | Likely cause | Fix |
|---|---|---|
| UI loads but searches fail | Missing or invalid `.env` keys | Check keys; restart Flask |
| `using_db: False` | Supabase env vars missing | Add `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` |
| People lookup auth error | LinkedIn session expired | Delete `not to share/linkedin/storage/`, re-login |
| Wrong/old company data | Cache hit | Clear cache per `HOW_TO_RUN.md` section 7 |
| Playwright error | Chromium not installed | `python -m playwright install chromium` |
| Extension can't connect | Flask not running | Start `python ui/app.py` first |

---

## CLI alternatives (no UI)

```powershell
# Company dossier
cd "web scraper"
python -m src "Apple"
python view_lastrun.py
cd ..

# Full lead pipeline (email → company → search → scrape)
cd "lead finder"
python main.py "name@company.com" --headed
cd ..

# LinkedIn scrape from URL list
cd "lead scraper"
python main.py
cd ..
```

URLs for lead scraper CLI go in `not to share/linkedin/urls.txt`.

---

## Suggested first actions for a new agent

1. Read `explanation.md` sections 1–3 and 11.
2. Verify `.env` exists and `using_db: True`.
3. Start Flask and open http://127.0.0.1:5000.
4. Run one Company Search and one People Lookup to see end-to-end behavior.
5. Only then begin the user's requested task.

---

## Quick command reference

```powershell
# Activate + run
.\not to share\.venv\Scripts\Activate.ps1
python ui\app.py

# Check Supabase
python -c "import sys; from pathlib import Path; from dotenv import load_dotenv; load_dotenv(Path('not to share')/'.env'); sys.path.insert(0,'web scraper'); from src.store import using_db; print(using_db())"

# Clear company cache
Remove-Item -Recurse -Force ".\not to share\web scraper\output\.cache", ".\not to share\web scraper\output\news", ".\not to share\web scraper\output\company" -ErrorAction SilentlyContinue
```

For full troubleshooting and cache commands, see `HOW_TO_RUN.md`.
