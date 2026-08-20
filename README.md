# Zuntra Lead Intelligence

**AI-powered company analysis for lead investigation, market dossiers, and people lookup.**

A dark-mode web app and Chrome extension that turns an email, company name, or LinkedIn search into a structured intelligence dossier — identity, financials, filings, news, and profiles — then stores it in Supabase.

![Python](https://img.shields.io/badge/Python-3.11%2B-blue)
![Flask](https://img.shields.io/badge/Flask-UI%20API-black)
![Playwright](https://img.shields.io/badge/Playwright-LinkedIn-2EAD33)
![Supabase](https://img.shields.io/badge/Supabase-Postgres-3FCF8E)
![Groq](https://img.shields.io/badge/LLM-Groq-orange)
![Chrome](https://img.shields.io/badge/Chrome-Extension-4285F4)
![License](https://img.shields.io/badge/License-MIT-lightgrey)

---

## Screenshots

### Dashboard — tracked companies, bookmarks, and industry search

![Dashboard](assets/dashboard.png)

### Lead — add an email, investigate, stop a run, and bookmark the company

![Lead investigation](assets/lead.png)

### Company Search — full dossier with description, exchange, and 52-week range

![Company Search](assets/company-search.png)

### People Lookup — person search, matches, look up one or all, stop mid-run

![LinkedIn Lookup](assets/linkedin-lookup.png)

---

## Features

| Capability | Detail |
|---|---|
| Dashboard | Companies tracked, bookmarks, search by name or industry (web app only) |
| Lead investigation | Email → company dossier + LinkedIn action; news on demand |
| Company Search | Identity, financials, filings, and news in one pipeline |
| People Lookup | Name, company, role, location, email, phone, or profile URL; role, company, and contact with sources |
| Chrome extension | Side-panel UI for Lead, Company, and People — same backend, no Dashboard tab |
| Progress + stop | Live progress bars; stop investigation or scrape without losing what already landed |
| Bookmarks | Pin companies; bookmarked cards surface first on the dashboard |
| Persistence | Dossiers, people, cache, news, workspace, and bookmarks in Supabase |

---

## Architecture

```text
Browser (front/ or extension/sidepanel.html)
        │
        ▼
Flask UI API (ui/app.py :5000)
        │
        ├── Company pipeline  → Yahoo · Finnhub · Wikipedia · SEC / NSE · news
        ├── Lead finder       → email parse → company (no news until Look up news)
        ├── LinkedIn scrape   → Playwright session
        └── Groq (optional)   → relevance + arranged overview text
                │
                ▼
        Supabase (companies · source_cache · news_days · workspace · bookmarks · people)
```

The UI talks only to Flask. Flask is the only client of Supabase.

---

## Web app vs Chrome extension

Both UIs share the same Flask backend and core logic. Use whichever fits your workflow.

| | Web app (`front/`) | Chrome extension (`extension/`) |
|---|---|---|
| **How to open** | http://127.0.0.1:5000 | Chrome side panel (toolbar icon) |
| **Tabs** | Dashboard, Lead, Company Search, People Lookup | Lead, Company Search, People Lookup |
| **Default tab** | Dashboard | Lead |
| **API calls** | Relative `/api/...` | Patched to `http://127.0.0.1:5000` |
| **Requires** | Flask running locally | Flask running locally |
| **Best for** | Browsing tracked companies, bookmarks, full dashboard | Quick lookups while browsing LinkedIn or email |

The extension is Manifest V3. It does not scrape LinkedIn from the browser directly — all Playwright automation runs in the Flask subprocess on your machine.

---

## Chrome extension setup

1. Complete the [Setup](#setup) steps and start Flask (`python ui\app.py`).
2. Open Chrome → **Extensions** → **Manage extensions**.
3. Enable **Developer mode**.
4. Click **Load unpacked** and select the `extension/` folder.
5. Click the Zuntra toolbar icon to open the side panel.

Extension files:

```text
extension/
├── manifest.json       # MV3 config, side panel, host permissions
├── background.js       # Opens side panel on icon click
├── sidepanel.html      # Lead / Company / People tabs
├── js/app.js           # Same logic as front/js/app.js with API base URL patch
├── css/style.css       # Shared dark-mode styles
└── css/sidebar.css     # Side-panel layout
```

Host permissions are limited to `http://127.0.0.1:5000` and `http://localhost:5000`.

---

## Project structure

```text
.
├── assets/                 # README screenshots
├── front/                  # Web SPA (HTML / CSS / JS)
├── extension/              # Chrome MV3 side-panel extension
├── ui/                     # Flask app and API
├── web scraper/            # Company intelligence pipeline
├── lead finder/            # Email → company orchestration + LinkedIn search
├── lead scraper/           # Playwright profile extraction + contact enrichment
├── supabase/schema.sql     # Tables + RLS policies
├── start.md                # Agent onboarding guide
├── explanation.md          # Deep architecture reference
├── HOW_TO_RUN.md           # Setup, CLI, cache, troubleshooting
├── requirements.txt
└── not to share/           # gitignored: .env, venv, cookies, LinkedIn session
```

---

## Requirements

- Python 3.11+
- Google Chrome (for the extension)
- Internet access for market, news, and LinkedIn requests
- A [Supabase](https://supabase.com) project (run `supabase/schema.sql` once)
- Playwright Chromium for LinkedIn and article body fetch

---

## Setup

```powershell
git clone <this-repo>
cd "ALL Knowing"

python -m venv "not to share\.venv"
.\not to share\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium
```

Create `not to share\.env` (never commit it). Names only:

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

| Variable | Used for |
|---|---|
| `FINNHUB_API_KEY` | Ticker resolve and profile |
| `ALPHA_VANTAGE_API_KEY` | Overview / financials |
| `SEC_USER_AGENT` | SEC EDGAR (`AppName you@email.com`) |
| `NEWSAPI_API_KEY` / `GNEWS_API_KEY` | News discovery |
| `GROQ_API_KEY` | News relevance and overview text |
| `LINKEDIN_EMAIL` / `LINKEDIN_PASSWORD` | Profile scrape session |
| `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` | Dossiers, cache, workspace, bookmarks, people |

Apply [`supabase/schema.sql`](supabase/schema.sql) in the Supabase SQL editor so `companies`, `source_cache`, `news_days`, `workspace`, `bookmarks`, and `people` exist.

For step-by-step setup, cache clearing, and CLI usage, see [`HOW_TO_RUN.md`](HOW_TO_RUN.md).

---

## Usage

```powershell
.\not to share\.venv\Scripts\Activate.ps1
python ui\app.py
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000) for the web app, or use the Chrome extension side panel.

| Tab | What you do |
|---|---|
| Dashboard | Browse tracked companies, search, open a card, bookmark (web app only) |
| Lead | Add an email → **Investigate** → **View** → **Look up news** if you want articles |
| Company Search | Name or ticker → full dossier including news |
| People Lookup | Name, company, role, location, email, phone, or profile URL → search matches → **Look up**; **Stop** cancels |

Ctrl+C in the terminal stops the server.

---

## Documentation

| File | Purpose |
|---|---|
| [`start.md`](start.md) | Onboarding guide for a new developer or AI agent |
| [`HOW_TO_RUN.md`](HOW_TO_RUN.md) | Setup, CLI commands, cache clearing, troubleshooting |
| [`explanation.md`](explanation.md) | Full architecture and component reference |

---

## Tech stack

| Layer | Tools |
|---|---|
| Language | Python 3.11+ |
| Web UI | Flask + vanilla JS SPA |
| Extension | Chrome MV3 side panel |
| Company data | Yahoo · Finnhub · Alpha Vantage · Wikipedia · SEC EDGAR · NSE |
| News | NewsAPI · GNews · Playwright article open |
| LLM | Groq |
| LinkedIn | Playwright |
| Store | Supabase (Postgres + JSONB) |

---

## Notes

- Company Search includes news; Lead investigation does not until **Look up news**
- LinkedIn automation can break when the site changes, and accounts can be restricted — keep volume low
- People lookup caches profile metadata in Supabase; photo/banner visuals are scraped on-demand when rendering results
- Without Playwright Chromium, company search still runs; article bodies stay thin
- Alpha Vantage has a daily soft cap (`av_day.json` under the private cache)
- The extension requires Flask to be running locally — it is not a standalone scraper

---

## Author

**Subhranil Ghosh** ([@w0lf-s](https://github.com/w0lf-s)) — Software Engineer focused on AI, backend systems, and scalable intelligent applications.

---

## License

MIT
