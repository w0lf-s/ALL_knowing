import random
import time
from pathlib import Path
from typing import Any

from src.auth import create_authenticated_context, open_playwright
from src.config import (
    URLS_PATH,
    Settings,
    get_settings,
)
from src.extract import extract_profile


def load_urls(path: Path = URLS_PATH) -> list[str]:
    if not path.exists():
        return []
    urls: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        urls.append(text)
    return urls


def run(
    settings: Settings | None = None,
    on_progress=None,
    urls: list[str] | None = None,
) -> list[dict[str, Any]]:
    settings = settings or get_settings()
    urls = [str(u).strip() for u in (urls or load_urls()) if str(u).strip()]
    if not urls:
        raise RuntimeError("No profile URLs provided")

    playwright = open_playwright()
    browser = None
    results: list[dict[str, Any]] = []
    try:
        browser, context = create_authenticated_context(playwright, settings)
        if settings.headless:
            settings.delay_min_seconds = min(float(settings.delay_min_seconds), 0.6)
            settings.delay_max_seconds = min(float(settings.delay_max_seconds), 1.2)
        page = context.new_page()
        total = len(urls)
        for index, url in enumerate(urls):
            if on_progress:
                on_progress({
                    "pct": int((index / max(total, 1)) * 100),
                    "step": f"Scraping profile {index + 1} of {total}",
                    "index": index + 1,
                    "total": total,
                })
            row = extract_profile(page, url)
            results.append(row)
            if on_progress:
                on_progress({
                    "pct": int(((index + 1) / max(total, 1)) * 100),
                    "step": f"Finished profile {index + 1} of {total}",
                    "index": index + 1,
                    "total": total,
                    "profile": row,
                })
            if row.get("error") == "auth_required":
                raise RuntimeError(f"Authentication required while visiting {url}")
            if index < len(urls) - 1:
                delay = random.uniform(
                    settings.delay_min_seconds, settings.delay_max_seconds
                )
                time.sleep(delay)
        context.close()
    finally:
        if browser is not None:
            browser.close()
        playwright.stop()

    return results
