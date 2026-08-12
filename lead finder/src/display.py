from __future__ import annotations

import json
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


def _clip(text: str, n: int = 280) -> str:
    t = " ".join(str(text or "").split())
    if len(t) <= n:
        return t
    return t[: n - 3].rstrip() + "..."


def display_report(result: dict[str, Any], console: Console | None = None) -> None:
    console = console or Console(force_terminal=True, legacy_windows=False)
    parsed = result.get("parsed") or {}
    console.print(
        Panel(
            Text.from_markup(
                f"[bold]{parsed.get('email') or '-'}[/bold]\n"
                f"Name: {parsed.get('name') or '-'}\n"
                f"Company: {parsed.get('company') or '-'}\n"
                f"Domain: {parsed.get('domain') or '-'}\n"
                f"Corporate: {'yes' if parsed.get('is_corporate') else 'no'}"
            ),
            title="Lead",
        )
    )

    if result.get("company_error"):
        console.print(Panel(str(result["company_error"]), title="Company error", style="red"))
    company = result.get("company")
    if company:
        overview = company.get("overview") or {}
        resolved = company.get("resolved") or {}
        news = (company.get("news") or {}).get("articles") or []
        lines = [
            f"{resolved.get('name') or company.get('query') or '-'} "
            f"({resolved.get('ticker') or '-'})",
            f"Industry: {overview.get('industry') or '-'}",
            f"Sector: {overview.get('sector') or '-'}",
            f"News articles: {len(news)}",
            "",
            _clip(overview.get("description") or overview.get("short_description") or ""),
        ]
        console.print(Panel("\n".join(lines).strip(), title="Company"))

    urls = result.get("candidate_urls") or []
    if result.get("search_error"):
        console.print(Panel(str(result["search_error"]), title="LinkedIn search error", style="red"))
    if urls:
        t = Table(show_header=True, title=None)
        t.add_column("#", style="dim", width=4)
        t.add_column("Profile URL")
        for i, url in enumerate(urls, start=1):
            t.add_row(str(i), url)
        console.print(Panel(t, title=f"Candidate profiles ({len(urls)})"))
    elif not result.get("search_error") and not result.get("skip_search"):
        console.print(Panel("No LinkedIn profile URLs found.", title="Candidate profiles"))

    if result.get("scrape_error"):
        console.print(Panel(str(result["scrape_error"]), title="LinkedIn scrape error", style="red"))
    profiles = result.get("profiles") or []
    for i, row in enumerate(profiles, start=1):
        fields = [
            ("Name", row.get("name")),
            ("Headline", row.get("headline")),
            ("Role", row.get("current_role")),
            ("Company", row.get("current_company")),
            ("Location", row.get("location")),
            ("Email", row.get("email")),
            ("Profile", row.get("linkedin_profile_url") or row.get("url")),
            ("About", _clip(row.get("about") or "", 400)),
            ("Error", row.get("error")),
        ]
        body = "\n".join(f"{k}: {v if v not in (None, '') else '-'}" for k, v in fields)
        console.print(Panel(body, title=f"Profile {i}"))

    if result.get("saved_to"):
        console.print(f"Saved run to {result['saved_to']}")
