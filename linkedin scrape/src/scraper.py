import csv
import json
import random
import time
from pathlib import Path
from typing import Any

from src.auth import create_authenticated_context, open_playwright
from src.config import (
    RESULTS_CSV,
    RESULTS_JSON,
    SUMMARY_JSON,
    URLS_PATH,
    Settings,
    ensure_dirs,
    get_settings,
)
from src.extract import extract_profile, is_successful_row


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


def _serialize_row(row: dict[str, Any]) -> dict[str, Any]:
    flat = dict(row)
    links = flat.get("links") or []
    other = flat.get("other_channels") or []
    if isinstance(links, list):
        rendered: list[str] = []
        for item in links:
            if isinstance(item, dict):
                title = str(item.get("title") or "").strip()
                url = str(item.get("url") or "").strip()
                if title and url:
                    rendered.append(f"{title} | {url}")
                elif url:
                    rendered.append(url)
            elif item:
                rendered.append(str(item))
        flat["links"] = "; ".join(rendered)
    flat["other_channels"] = "; ".join(other) if isinstance(other, list) else other
    return flat


def write_results(rows: list[dict[str, Any]]) -> None:
    ensure_dirs()
    RESULTS_JSON.write_text(
        json.dumps(rows, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    fieldnames = [
        "url",
        "name",
        "headline",
        "current_role",
        "current_company",
        "location",
        "about",
        "email",
        "phone",
        "links",
        "twitter",
        "linkedin_profile_url",
        "other_channels",
        "error",
    ]
    with RESULTS_CSV.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(_serialize_row(row))


def write_summary(total: int, success: int, failed: int) -> None:
    ensure_dirs()
    SUMMARY_JSON.write_text(
        json.dumps(
            {
                "total": total,
                "success": success,
                "failed": failed,
                "results_json": str(RESULTS_JSON),
                "results_csv": str(RESULTS_CSV),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def run(settings: Settings | None = None, on_progress=None) -> list[dict[str, Any]]:
    settings = settings or get_settings()
    ensure_dirs()
    urls = load_urls()
    if not urls:
        write_results([])
        write_summary(0, 0, 0)
        raise RuntimeError(
            "No profile URLs found in urls.txt. Add one URL per line without a leading #."
        )

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
                write_results(results)
                success = sum(1 for r in results if is_successful_row(r))
                write_summary(len(results), success, len(results) - success)
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

    write_results(results)
    success = sum(1 for r in results if is_successful_row(r))
    write_summary(len(results), success, len(results) - success)
    return results
