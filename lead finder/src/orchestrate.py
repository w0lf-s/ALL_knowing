from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

from src.config import (
    CANDIDATE_URLS_PATH,
    LAST_RUN_JSON,
    LINKEDIN_SCRAPE_DIR,
    VENV_PYTHON,
    WEB_SCRAPER_DIR,
    ensure_dirs,
)
from src.email_parse import ParsedEmail, classify_email
from src.linkedin_search import search_people_urls, write_urls
from src.path_swap import linkedin_src_path


def _python() -> str:
    if VENV_PYTHON.exists():
        return str(VENV_PYTHON)
    return sys.executable


def run_company_pipeline(company: str) -> dict[str, Any]:
    script = (
        "import asyncio, json, sys\n"
        "from src.pipeline import run_pipeline\n"
        "d = asyncio.run(run_pipeline(sys.argv[1], use_groq=True, use_playwright=True))\n"
        "print(json.dumps(d.model_dump(), default=str))\n"
    )
    result = subprocess.run(
        [_python(), "-c", script, company],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=str(WEB_SCRAPER_DIR),
        env={**os.environ},
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "company pipeline failed").strip()
        raise RuntimeError(err.splitlines()[-1] if err else "company pipeline failed")
    lines = [ln for ln in (result.stdout or "").splitlines() if ln.strip()]
    if not lines:
        raise RuntimeError("company pipeline returned no output")
    return json.loads(lines[-1])


def run_linkedin_scrape(urls: list[str], *, headless: bool = True) -> list[dict[str, Any]]:
    if not urls:
        return []
    with linkedin_src_path():
        from src.config import URLS_PATH, get_settings
        from src.scraper import run

        write_urls(URLS_PATH, urls)
        settings = get_settings()
        settings.headless = headless
        return run(settings)


def run_lead_finder(
    email: str,
    *,
    max_profiles: int = 5,
    no_company: bool = False,
    no_scrape: bool = False,
    headless: bool = True,
) -> dict[str, Any]:
    ensure_dirs()
    parsed: ParsedEmail = classify_email(email)
    out: dict[str, Any] = {
        "parsed": parsed.to_dict(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "company": None,
        "company_error": None,
        "candidate_urls": [],
        "search_error": None,
        "profiles": [],
        "scrape_error": None,
        "skip_search": False,
        "saved_to": str(LAST_RUN_JSON),
    }

    if parsed.is_corporate and parsed.company and not no_company:
        try:
            out["company"] = run_company_pipeline(parsed.company)
        except Exception as exc:
            out["company_error"] = str(exc)
    elif no_company:
        out["company_error"] = None
    elif not parsed.is_corporate:
        out["company_error"] = "Skipped company search (free email domain)"

    if not parsed.name:
        out["search_error"] = "Could not derive a person name from the email local-part"
        out["skip_search"] = True
    else:
        try:
            urls = search_people_urls(
                parsed.name,
                parsed.company if parsed.is_corporate else "",
                max_profiles=max_profiles,
                headless=headless,
            )
            out["candidate_urls"] = urls
            write_urls(CANDIDATE_URLS_PATH, urls)
        except Exception as exc:
            out["search_error"] = str(exc)

    if not no_scrape and out["candidate_urls"]:
        try:
            out["profiles"] = run_linkedin_scrape(
                out["candidate_urls"],
                headless=headless,
            )
        except Exception as exc:
            out["scrape_error"] = str(exc)

    LAST_RUN_JSON.write_text(
        json.dumps(out, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return out
