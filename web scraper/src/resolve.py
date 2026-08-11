from __future__ import annotations

import os

from src.adapters import CompanyContext
from src.adapters.finnhub import pick_best_symbol, search_symbol
from src.adapters.sec_edgar import load_ticker_map, resolve_cik
from src.adapters.wikipedia import fetch_wikipedia
from src.http import HttpClient
from src.rate_limit import RateLimits


async def resolve_identity(http: HttpClient, limits: RateLimits, query: str) -> CompanyContext:
    ctx = CompanyContext(query=query)
    fh = await search_symbol(http, limits, query)
    if fh.ok and isinstance(fh.data, dict):
        search = fh.data.get("search") or {}
        ticker, name = pick_best_symbol(search, query)
        ctx.ticker = ticker
        ctx.name = name or query
    else:
        ctx.name = query

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
