from __future__ import annotations

import os
from typing import Any

from src.adapters import CompanyContext, SourceResult
from src.cache import get_cached, set_cached
from src.http import HttpClient, sanitize_error
from src.rate_limit import RateLimits

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"


async def load_ticker_map(http: HttpClient, limits: RateLimits, user_agent: str) -> dict[str, Any]:
    cached = get_cached("sec", "company_tickers", 86400)
    if cached is not None:
        return cached
    await limits.sec.acquire()
    data = await http.get_json(TICKERS_URL, headers={"User-Agent": user_agent})
    set_cached("sec", "company_tickers", data)
    return data


def resolve_cik(ticker_map: dict[str, Any], ticker: str | None) -> tuple[str | None, str | None, str | None]:
    if not ticker:
        return None, None, None
    want = ticker.upper().strip()
    for row in ticker_map.values() if isinstance(ticker_map, dict) else []:
        if not isinstance(row, dict):
            continue
        if str(row.get("ticker", "")).upper() == want:
            cik = str(row.get("cik_str", "")).zfill(10)
            title = row.get("title")
            return cik, title, None
    return None, None, None


async def fetch_filings(
    http: HttpClient,
    limits: RateLimits,
    ctx: CompanyContext,
) -> SourceResult:
    user_agent = os.getenv("SEC_USER_AGENT", "").strip() or "company_search contact@example.com"
    if not ctx.cik:
        try:
            ticker_map = await load_ticker_map(http, limits, user_agent)
            cik, title, _ = resolve_cik(ticker_map, ctx.ticker)
            if cik:
                ctx.cik = cik
                if title and not ctx.name:
                    ctx.name = title
        except Exception as exc:
            return SourceResult("sec_edgar", False, error=sanitize_error(exc))
    if not ctx.cik:
        return SourceResult("sec_edgar", False, error="missing_cik")
    cached = get_cached("sec_submissions", ctx.cik, 86400)
    if cached is not None:
        return SourceResult("sec_edgar", True, data=cached)
    try:
        await limits.sec.acquire()
        cik_int = str(int(ctx.cik))
        url = f"https://data.sec.gov/submissions/CIK{ctx.cik}.json"
        data = await http.get_json(url, headers={"User-Agent": user_agent})
        set_cached("sec_submissions", ctx.cik, data)
        return SourceResult("sec_edgar", True, data=data)
    except Exception as exc:
        return SourceResult("sec_edgar", False, error=sanitize_error(exc))
