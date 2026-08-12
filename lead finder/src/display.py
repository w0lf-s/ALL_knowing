from __future__ import annotations

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


def _console(console: Console | None) -> Console:
    return console or Console(force_terminal=True, legacy_windows=False)


def show_step(message: str, console: Console | None = None) -> None:
    _console(console).print(f"\n[bold cyan]→ {message}[/bold cyan]")


def show_lead(parsed: dict[str, Any], console: Console | None = None) -> None:
    c = _console(console)
    c.print(
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


def show_company(company: dict[str, Any] | None, error: str | None = None, console: Console | None = None) -> None:
    c = _console(console)
    if error:
        c.print(Panel(str(error), title="Company (web scraper)", style="red"))
        return
    if not company:
        return
    overview = company.get("overview") or {}
    resolved = company.get("resolved") or {}
    financials = company.get("financials") or {}
    news = (company.get("news") or {}).get("articles") or []
    filings = company.get("filings") or []

    lines = [
        f"{resolved.get('name') or company.get('query') or '-'} "
        f"({resolved.get('ticker') or '-'})",
        f"Industry: {overview.get('industry') or '-'}",
        f"Sector: {overview.get('sector') or '-'}",
        f"HQ: {overview.get('headquarters') or '-'}",
        f"Website: {overview.get('website') or '-'}",
        f"Employees: {overview.get('employees') or '-'}",
        "",
        _clip(overview.get("description") or overview.get("short_description") or "", 500),
    ]
    if financials.get("market_cap") or financials.get("revenue") or financials.get("pe_ratio"):
        lines.append("")
        lines.append(
            "Financials: "
            f"mkt_cap={financials.get('market_cap') or '-'}  "
            f"revenue={financials.get('revenue') or '-'}  "
            f"pe={financials.get('pe_ratio') or '-'}"
        )
    lines.append(f"News: {len(news)}  |  Filings: {len(filings)}")
    c.print(Panel("\n".join(lines).strip(), title="Company (web scraper)"))

    if news:
        t = Table(show_header=True, box=None, padding=(0, 1))
        t.add_column("Title", overflow="fold")
        t.add_column("Source", style="dim", width=18)
        for article in news[:5]:
            t.add_row(
                _clip(article.get("title") or "Untitled", 90),
                str(article.get("source_name") or "-")[:18],
            )
        c.print(Panel(t, title="Company news"))


def show_candidate_urls(
    urls: list[str],
    error: str | None = None,
    *,
    skipped: bool = False,
    console: Console | None = None,
) -> None:
    c = _console(console)
    if error:
        c.print(Panel(str(error), title="LinkedIn search", style="red"))
        return
    if skipped:
        return
    if not urls:
        c.print(Panel("No LinkedIn profile URLs found.", title="LinkedIn candidates"))
        return
    t = Table(show_header=True)
    t.add_column("#", style="dim", width=4)
    t.add_column("Profile URL")
    for i, url in enumerate(urls, start=1):
        t.add_row(str(i), url)
    c.print(Panel(t, title=f"LinkedIn candidates ({len(urls)})"))


def show_profiles(
    profiles: list[dict[str, Any]],
    error: str | None = None,
    console: Console | None = None,
) -> None:
    c = _console(console)
    if error:
        c.print(Panel(str(error), title="LinkedIn scrape", style="red"))
        return
    if not profiles:
        return
    for i, row in enumerate(profiles, start=1):
        fields = [
            ("Name", row.get("name")),
            ("Headline", row.get("headline")),
            ("Role", row.get("current_role")),
            ("Company", row.get("current_company")),
            ("Location", row.get("location")),
            ("Email", row.get("email")),
            ("Phone", row.get("phone")),
            ("Profile", row.get("linkedin_profile_url") or row.get("url")),
            ("About", _clip(row.get("about") or "", 400)),
            ("Error", row.get("error")),
        ]
        body = "\n".join(f"{k}: {v if v not in (None, '') else '-'}" for k, v in fields)
        c.print(Panel(body, title=f"LinkedIn profile {i}"))


def display_report(result: dict[str, Any], console: Console | None = None) -> None:
    c = _console(console)
    show_lead(result.get("parsed") or {}, c)
    show_company(result.get("company"), result.get("company_error"), c)
    show_candidate_urls(
        result.get("candidate_urls") or [],
        result.get("search_error"),
        skipped=bool(result.get("skip_search")),
        console=c,
    )
    show_profiles(result.get("profiles") or [], result.get("scrape_error"), c)
    if result.get("saved_to"):
        c.print(f"Saved run to {result['saved_to']}")
