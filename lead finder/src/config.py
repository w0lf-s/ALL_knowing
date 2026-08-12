from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ROOT.parent
SECRETS_DIR = REPO_ROOT / "not to share"
PRIVATE_DIR = SECRETS_DIR / "lead finder"
OUTPUT_DIR = PRIVATE_DIR / "output"
LAST_RUN_JSON = OUTPUT_DIR / "last_run.json"
CANDIDATE_URLS_PATH = OUTPUT_DIR / "candidate_urls.txt"
VENV_PYTHON = SECRETS_DIR / ".venv" / "Scripts" / "python.exe"
WEB_SCRAPER_DIR = REPO_ROOT / "web scraper"
LINKEDIN_SCRAPE_DIR = REPO_ROOT / "linkedin scrape"


def ensure_dirs() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
