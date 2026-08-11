# LinkedIn Profile Scraper (Playwright)

Automated extraction of role, company, and available contact fields from LinkedIn profile URLs you provide.

LinkedIn’s Terms of Service disallow automated scraping. Use only on accounts and data you are authorized to access. Keep volume low. Selectors break often, and accounts can be restricted.

## Setup

1. Create a virtual environment and install dependencies:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

2. Copy `.env.example` to `.env` and set `LINKEDIN_EMAIL` and `LINKEDIN_PASSWORD`.

3. Put profile URLs in `urls.txt` (one per line). Lines starting with `#` are ignored.

## Run

```bash
python main.py
```

A Chromium window opens (headed by default). Complete any LinkedIn checkpoint or 2FA in that window if prompted. Session cookies are saved to `storage/linkedin_state.json` for reuse. Results print in the terminal when the run finishes.

View saved results without scraping:

```bash
python main.py --view
```

## Output

- Terminal CLI summary after each run (or via `--view`)
- `output/results.json` — full records
- `output/results.csv` — spreadsheet-friendly rows
- `output/run_summary.json` — total / success / failed counts

Contact email and phone appear only when LinkedIn shows them on the Contact info panel for your account.
