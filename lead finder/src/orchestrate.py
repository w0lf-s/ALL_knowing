from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

from rich.console import Console

from src.config import (
    CANDIDATE_URLS_PATH,
    LAST_RUN_JSON,
    VENV_PYTHON,
    WEB_SCRAPER_DIR,
    ensure_dirs,
)
from src.display import (
    show_candidate_urls,
    show_company,
    show_lead,
    show_profiles,
    show_step,
)
from src.email_parse import ParsedEmail, classify_email
from src.linkedin_search import search_people_urls, write_urls
from src.path_swap import linkedin_src_path


def _python() -> str:
    if VENV_PYTHON.exists():
        return str(VENV_PYTHON)
    return sys.executable


def run_company_pipeline(company: str, *, fast: bool = False) -> dict[str, Any]:
    use_groq = not fast
    use_playwright = not fast
    skip_news = fast
    lite = fast
    timeout = 60 if fast else 300
    script = (
        "import asyncio, json, sys\n"
        "from src.pipeline import run_pipeline\n"
        f"d = asyncio.run(run_pipeline(sys.argv[1], use_groq={use_groq}, use_playwright={use_playwright}, skip_news={skip_news}, lite={lite}))\n"
        "print(json.dumps(d.model_dump(), default=str))\n"
    )
    result = subprocess.run(
        [_python(), "-c", script, company],
        capture_output=True,
        text=True,
        timeout=timeout,
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
        if headless:
            settings.checkpoint_timeout_seconds = min(
                settings.checkpoint_timeout_seconds, 20
            )
            settings.delay_min_seconds = min(settings.delay_min_seconds, 1.0)
            settings.delay_max_seconds = min(settings.delay_max_seconds, 2.0)
        return run(settings)


def run_lead_finder(
    email: str,
    *,
    max_profiles: int = 5,
    no_company: bool = False,
    no_scrape: bool = False,
    no_search: bool = False,
    headless: bool = True,
    live: bool = True,
) -> dict[str, Any]:
    ensure_dirs()
    console = Console(force_terminal=True, legacy_windows=False) if live else None
    parsed: ParsedEmail = classify_email(email)
    out: dict[str, Any] = {
        "parsed": parsed.to_dict(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "company": None,
        "company_error": None,
        "candidate_urls": [],
        "candidates": [],
        "search_error": None,
        "profiles": [],
        "scrape_error": None,
        "skip_search": False,
        "saved_to": str(LAST_RUN_JSON),
    }

    if live:
        show_step("Parsed viewer email", console)
        show_lead(out["parsed"], console)

    if parsed.is_corporate and parsed.company and not no_company:
        if live:
            show_step(f"Running web scraper for company: {parsed.company}", console)
        try:
            out["company"] = run_company_pipeline(parsed.company, fast=not live)
        except Exception as exc:
            out["company_error"] = str(exc)
        if live:
            show_company(out["company"], out["company_error"], console)
    elif not parsed.is_corporate:
        out["company_error"] = "Skipped company search (free email domain)"
        if live:
            show_company(None, out["company_error"], console)

    if no_search:
        out["skip_search"] = True
    elif not parsed.name:
        out["search_error"] = "Could not derive a person name from the email local-part"
        out["skip_search"] = True
        if live:
            show_candidate_urls([], out["search_error"], console=console)
    else:
        query_bits = " ".join(
            x for x in (parsed.name, parsed.company if parsed.is_corporate else "") if x
        )
        if live:
            show_step(f"Searching LinkedIn people for: {query_bits}", console)
        try:
            candidates = search_people_urls(
                parsed.name,
                parsed.company if parsed.is_corporate else "",
                max_profiles=max_profiles,
                headless=headless,
            )
            out["candidates"] = candidates
            out["candidate_urls"] = [c["url"] for c in candidates]
            write_urls(CANDIDATE_URLS_PATH, out["candidate_urls"])
        except Exception as exc:
            out["search_error"] = str(exc)
        if live:
            show_candidate_urls(
                out.get("candidates") or [],
                out["search_error"],
                skipped=False,
                console=console,
            )

    if not no_scrape and out["candidate_urls"]:
        if live:
            show_step(
                f"Scraping {len(out['candidate_urls'])} LinkedIn profile(s)",
                console,
            )
        try:
            out["profiles"] = run_linkedin_scrape(
                out["candidate_urls"],
                headless=headless,
            )
        except Exception as exc:
            out["scrape_error"] = str(exc)
        if live:
            show_profiles(out["profiles"], out["scrape_error"], console)
    elif no_scrape and live and out["candidate_urls"]:
        show_step("Skipped profile scrape (--no-scrape)", console)

    LAST_RUN_JSON.write_text(
        json.dumps(out, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    if live and out.get("saved_to"):
        console.print(f"\nSaved run to {out['saved_to']}")
    return out
