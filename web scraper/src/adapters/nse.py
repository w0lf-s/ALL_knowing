from __future__ import annotations

from src.adapters import CompanyContext, SourceResult
from src.adapters.yahoo import is_india_symbol, nse_code
from src.cache import get_cached, set_cached
from src.http import HttpClient, sanitize_error

NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/get-quotes/equity",
    "Origin": "https://www.nseindia.com",
}


async def fetch_nse_announcements(http: HttpClient, ctx: CompanyContext) -> SourceResult:
    code = nse_code(ctx.ticker)
    if not code:
        return SourceResult("nse", False, error="missing_ticker")
    exch = " ".join(ctx.exchanges or []).upper()
    india_ex = any(x in exch for x in ("NSE", "BSE", "NSI", "BOM", "NATIONAL STOCK"))
    if not is_india_symbol(ctx.ticker) and not india_ex:
        return SourceResult("nse", False, error="not_india_listing")
    cached = get_cached("nse_announcements", code, 6 * 3600)
    if cached is not None:
        return SourceResult("nse", True, data=cached)
    try:
        await http.get_text(
            "https://www.nseindia.com/",
            headers={**NSE_HEADERS, "Accept": "text/html,application/xhtml+xml"},
            retries=1,
            timeout=8.0,
        )
        await http.get_text(
            "https://www.nseindia.com/get-quotes/equity",
            params={"symbol": code},
            headers={**NSE_HEADERS, "Accept": "text/html,application/xhtml+xml", "Referer": "https://www.nseindia.com/"},
            retries=1,
            timeout=8.0,
        )
        data = None
        last_exc = None
        for path in (
            "https://www.nseindia.com/api/corporate-announcements",
            "https://www.nseindia.com/api/corporates-announcements",
        ):
            try:
                data = await http.get_json(
                    path,
                    params={"index": "equities", "symbol": code},
                    headers=NSE_HEADERS,
                    retries=1,
                    timeout=10.0,
                )
                break
            except Exception as exc:
                last_exc = exc
                data = None
        if data is None:
            raise last_exc or RuntimeError("nse_request_failed")
        rows = data if isinstance(data, list) else (data or {}).get("data") or data or []
        if not isinstance(rows, list) or not rows:
            return SourceResult("nse", False, error="empty_announcements")
        items = []
        for row in rows[:20]:
            if not isinstance(row, dict):
                continue
            items.append(
                {
                    "form": row.get("desc") or row.get("attchmntText") or "Announcement",
                    "filed_at": row.get("an_dt") or row.get("sort_date") or row.get("exdt"),
                    "title": row.get("attchmntText") or row.get("sm_name") or row.get("subject"),
                    "url": row.get("attchmntFile") or row.get("file") or None,
                }
            )
        payload = {"symbol": code, "items": items}
        set_cached("nse_announcements", code, payload)
        return SourceResult("nse", True, data=payload)
    except Exception as exc:
        return SourceResult("nse", False, error=sanitize_error(exc))
