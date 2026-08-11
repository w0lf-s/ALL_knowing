from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent
SECRETS_DIR = ROOT.parent / "not to share"
PRIVATE_DIR = SECRETS_DIR / "linkedin"
STORAGE_DIR = PRIVATE_DIR / "storage"
OUTPUT_DIR = PRIVATE_DIR / "output"
STATE_PATH = STORAGE_DIR / "linkedin_state.json"
URLS_PATH = PRIVATE_DIR / "urls.txt"
RESULTS_JSON = OUTPUT_DIR / "results.json"
RESULTS_CSV = OUTPUT_DIR / "results.csv"
SUMMARY_JSON = OUTPUT_DIR / "run_summary.json"
DEBUG_JSON = OUTPUT_DIR / "last_page_debug.json"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(SECRETS_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    linkedin_email: str = ""
    linkedin_password: str = ""
    delay_min_seconds: float = 3.0
    delay_max_seconds: float = 8.0
    headless: bool = False
    checkpoint_timeout_seconds: int = 300


def get_settings() -> Settings:
    return Settings()


def ensure_dirs() -> None:
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
