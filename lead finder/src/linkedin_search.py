from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote_plus

from src.path_swap import linkedin_src_path

_PROFILE_RE = re.compile(
    r"https?://(?:www\.)?linkedin\.com/in/[A-Za-z0-9\-_%]+/?",
    re.IGNORECASE,
)


def _normalize_profile_url(url: str) -> str | None:
    match = _PROFILE_RE.search(url or "")
    if not match:
        return None
    cleaned = match.group(0).split("?")[0].rstrip("/")
    if cleaned.lower().endswith("/in"):
        return None
    return cleaned


def _search_url(name: str, company: str) -> str:
    keywords = " ".join(part for part in (name, company) if part).strip()
    encoded = quote_plus(keywords)
    return f"https://www.linkedin.com/search/results/people/?keywords={encoded}"


def search_people_urls(
    name: str,
    company: str = "",
    *,
    max_profiles: int = 5,
    headless: bool = True,
) -> list[str]:
    with linkedin_src_path():
        from src.auth import create_authenticated_context, open_playwright
        from src.config import get_settings

        settings = get_settings()
        settings.headless = headless

        playwright = open_playwright()
        browser = None
        found: list[str] = []
        seen: set[str] = set()
        try:
            browser, context = create_authenticated_context(playwright, settings)
            page = context.new_page()
            page.goto(
                _search_url(name, company),
                wait_until="domcontentloaded",
                timeout=90000,
            )
            page.wait_for_timeout(3000)
            try:
                page.wait_for_selector('a[href*="/in/"]', timeout=15000)
            except Exception:
                pass
            for _ in range(3):
                page.mouse.wheel(0, 2400)
                page.wait_for_timeout(800)
            hrefs = page.eval_on_selector_all(
                'a[href*="/in/"]',
                "els => els.map(e => e.href)",
            )
            for href in hrefs or []:
                normalized = _normalize_profile_url(str(href))
                if not normalized:
                    continue
                key = normalized.lower()
                if key in seen:
                    continue
                seen.add(key)
                found.append(normalized)
                if len(found) >= max_profiles:
                    break
            page.close()
            context.close()
        finally:
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass
            try:
                playwright.stop()
            except Exception:
                pass
        return found


def write_urls(path: Path, urls: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(urls) + ("\n" if urls else ""), encoding="utf-8")
