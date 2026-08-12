from __future__ import annotations

import os

from src.adapters import CompanyContext
from src.adapters.finnhub import pick_best_symbol, search_symbol
from src.adapters.sec_edgar import load_ticker_map, resolve_cik
from src.adapters.wikipedia import fetch_wikipedia
from src.http import HttpClient
from src.rate_limit import RateLimits

_SEARCH_ALIASES: dict[str, list[str]] = {
    "google": ["Alphabet", "GOOGL"],
    "youtube": ["Alphabet", "GOOGL"],
    "instagram": ["Meta", "META"],
    "facebook": ["Meta", "META"],
    "whatsapp": ["Meta", "META"],
    "aws": ["Amazon", "AMZN"],
    "linkedin": ["Microsoft", "MSFT"],
}


async def _lookup_ticker(
    http: HttpClient,
    limits: RateLimits,
    query: str,
) -> tuple[str | None, str | None]:
    terms = [query]
    for alt in _SEARCH_ALIASES.get(query.lower().strip(), []):
        if alt not in terms:
            terms.append(alt)
    for term in terms:
        fh = await search_symbol(http, limits, term)
        if not fh.ok or not isinstance(fh.data, dict):
            continue
        search = fh.data.get("search") or {}
        if not (search.get("result") or []):
            continue
        ticker, name = pick_best_symbol(search, term)
        if ticker:
            return ticker, name or query
    return None, query


async def resolve_identity(http: HttpClient, limits: RateLimits, query: str) -> CompanyContext:
    ctx = CompanyContext(query=query)
    ticker, name = await _lookup_ticker(http, limits, query)
    ctx.ticker = ticker
    ctx.name = name or query

    user_agent = os.getenv("SEC_USER_AGENT", "").strip() or "company_search contact@example.com"
    if ctx.ticker:
        try:
            ticker_map = await load_ticker_map(http, limits, user_agent)
            cik, title, _ = resolve_cik(ticker_map, ctx.ticker)
            ctx.cik = cik
            if title:
                ctx.name = title
        except Exception:
            pass

    wiki = await fetch_wikipedia(http, ctx)
    if wiki.ok and isinstance(wiki.data, dict):
        ctx.wiki_title = wiki.data.get("title")

    return ctx
