from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRIVATE_DIR = ROOT.parent / "not to share" / "web scraper"
OUTPUT = PRIVATE_DIR / "output"
CACHE = OUTPUT / ".cache"
RAW_DIR = OUTPUT / "raw"
COMPANY_DIR = OUTPUT / "company"
NEWS_DIR = OUTPUT / "news"
LASTRUN = PRIVATE_DIR / "lastrun.json"


def company_key(query: str) -> str:
    s = "".join(ch.lower() if ch.isalnum() else "-" for ch in query.strip())
    while "--" in s:
        s = s.replace("--", "-")
    return s.strip("-") or "unknown"


def ensure_dirs() -> None:
    for p in (OUTPUT, CACHE, RAW_DIR, COMPANY_DIR, NEWS_DIR):
        p.mkdir(parents=True, exist_ok=True)
