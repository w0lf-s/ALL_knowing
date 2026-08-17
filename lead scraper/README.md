# Lead scraper (Playwright)

Extracts role, company, and visible contact fields from LinkedIn profile URLs, then checks public company/team pages, profile links, and GitHub for extra emails and phones.

Use only on accounts and data you are authorized to access. Keep volume low.

## Setup

```powershell
.\not to share\.venv\Scripts\Activate.ps1
```

Set `LINKEDIN_EMAIL` and `LINKEDIN_PASSWORD` in `not to share\.env`.

## Run

```powershell
python main.py
```

Session cookies are saved to `not to share\linkedin\storage\linkedin_state.json`.
