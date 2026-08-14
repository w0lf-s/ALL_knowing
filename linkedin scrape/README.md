# LinkedIn Profile Scraper (Playwright)

Automated extraction of role, company, and available contact fields from LinkedIn profile URLs you provide.

LinkedIn’s Terms of Service disallow automated scraping. Use only on accounts and data you are authorized to access. Keep volume low. Selectors break often, and accounts can be restricted.

## Setup

Use the shared venv and the single env file under `not to share\`:

```powershell
.\not to share\.venv\Scripts\Activate.ps1
```

Set `LINKEDIN_EMAIL` and `LINKEDIN_PASSWORD` in `not to share\.env`. Put profile URLs in `not to share\linkedin\urls.txt` (one per line).

## Run

```powershell
python main.py
```

A Chromium window opens (headed by default). Complete any LinkedIn checkpoint or 2FA in that window if prompted. Session cookies are saved to `not to share\linkedin\storage\linkedin_state.json` for reuse.

View saved results without scraping:

```powershell
python main.py --view
```

## Output

Private outputs live under `not to share\linkedin\output\`:

- `results.json`
- `results.csv`
- `run_summary.json`
