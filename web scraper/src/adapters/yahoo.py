from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from src.adapters import CompanyContext, SourceResult
from src.cache import get_cached, set_cached
from src.http import HttpClient, sanitize_error

YAHOO_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

_INDIA_HINT = re.compile(
    r"\b(india|indian|nse|bse|pvt|private|limited|ltd)\b|\.(ns|bo|nse|bse)\b",
    re.I,
)


def is_india_symbol(ticker: str | None) -> bool:
    if not ticker:
        return False
    return ticker.upper().split(".", 1)[-1] in {"NS", "BO", "NSE", "BSE"} if "." in ticker else False


def nse_code(ticker: str | None) -> str | None:
    if not ticker:
        return None
    base = ticker.upper().strip()
    if "." in base:
        base = base.split(".", 1)[0]
    return base or None


def _raw(obj: Any, key: str) -> Any:
    if not isinstance(obj, dict):
        return None
    node = obj.get(key)
    if isinstance(node, dict) and "raw" in node:
        return node.get("raw")
    return node


def pick_yahoo_symbol(quotes: list[dict[str, Any]], query: str) -> tuple[str | None, str | None, str | None]:
    if not quotes:
        return None, None, None
    q = query.strip()
    q_upper = q.upper()
    q_lower = q.lower()
    prefer_india = bool(_INDIA_HINT.search(q))
    best: tuple[int, str, str | None, str | None] | None = None
    for item in quotes:
        typ = str(item.get("quoteType") or "").upper()
        if typ and typ not in {"EQUITY", "ETF", ""}:
            continue
        sym = str(item.get("symbol") or "").upper().strip()
        if not sym:
            continue
        name = item.get("shortname") or item.get("longname") or item.get("name")
        exch = str(item.get("exchDisp") or item.get("exchange") or "")
        exch_u = exch.upper()
        score = 0
        if sym == q_upper or sym.split(".", 1)[0] == q_upper:
            score += 80
        if name and q_lower in str(name).lower():
            score += 40
        if str(name or "").lower().startswith(q_lower[: min(8, len(q_lower))]):
            score += 20
        if exch_u in {"NMS", "NYQ", "NASDAQ", "NYSE", "NGM"}:
            score += 25 if not prefer_india else 5
        if exch_u in {"NSE", "NSI"} or sym.endswith(".NS"):
            score += 50 if prefer_india else 28
        elif exch_u in {"BSE", "BOM"} or sym.endswith(".BO"):
            score += 20 if prefer_india else 12
        elif is_india_symbol(sym):
            score += 45 if prefer_india else 20
        if best is None or score > best[0]:
            best = (score, sym, name, exch)
    if best and best[0] > 0:
        return best[1], best[2], best[3]
    first = quotes[0]
    return (
        (first.get("symbol") or "").upper() or None,
        first.get("shortname") or first.get("longname"),
        first.get("exchDisp") or first.get("exchange"),
    )


async def search_yahoo(http: HttpClient, query: str) -> SourceResult:
    cached = get_cached("yahoo_search", query.lower(), 86400)
    if cached is not None:
        return SourceResult("yahoo", True, data={"search": cached, "cached": True})
    try:
        data = await http.get_json(
            "https://query1.finance.yahoo.com/v1/finance/search",
            params={"q": query, "quotesCount": 12, "newsCount": 0},
            headers=YAHOO_HEADERS,
            retries=2,
            timeout=10.0,
        )
        quotes = (data or {}).get("quotes") or []
        set_cached("yahoo_search", query.lower(), quotes)
        return SourceResult("yahoo", True, data={"search": quotes})
    except Exception as exc:
        return SourceResult("yahoo", False, error=sanitize_error(exc))


def _wrap_raw(v: Any) -> dict[str, Any] | None:
    if v is None:
        return None
    return {"raw": v, "fmt": str(v)}


def _quote_from_v7(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "price": {
            "longName": item.get("longName") or item.get("shortName"),
            "shortName": item.get("shortName"),
            "exchangeName": item.get("fullExchangeName") or item.get("exchange"),
            "exchange": item.get("exchange"),
            "marketCap": _wrap_raw(item.get("marketCap")),
            "currency": item.get("currency") or item.get("financialCurrency"),
        },
        "summaryDetail": {
            "marketCap": _wrap_raw(item.get("marketCap")),
            "trailingPE": _wrap_raw(item.get("trailingPE")),
            "fiftyTwoWeekHigh": _wrap_raw(item.get("fiftyTwoWeekHigh")),
            "fiftyTwoWeekLow": _wrap_raw(item.get("fiftyTwoWeekLow")),
            "dividendYield": _wrap_raw(item.get("trailingAnnualDividendYield") or item.get("dividendYield")),
            "beta": _wrap_raw(item.get("beta")),
            "currency": item.get("currency") or item.get("financialCurrency"),
        },
        "defaultKeyStatistics": {
            "trailingEps": _wrap_raw(item.get("epsTrailingTwelveMonths")),
            "enterpriseValue": _wrap_raw(item.get("enterpriseValue")),
            "beta": _wrap_raw(item.get("beta")),
            "sharesOutstanding": _wrap_raw(item.get("sharesOutstanding")),
        },
        "financialData": {
            "totalRevenue": _wrap_raw(item.get("totalRevenue") or item.get("revenue")),
            "trailingPE": _wrap_raw(item.get("trailingPE")),
            "profitMargins": _wrap_raw(item.get("profitMargins")),
            "ebitda": _wrap_raw(item.get("ebitda")),
        },
        "summaryProfile": {
            "industry": item.get("industry"),
            "sector": item.get("sector"),
            "website": item.get("website"),
            "city": item.get("city"),
            "state": item.get("state"),
            "country": item.get("country"),
            "address1": item.get("address1"),
            "longBusinessSummary": item.get("longBusinessSummary"),
            "fullTimeEmployees": item.get("fullTimeEmployees"),
            "phone": item.get("phone"),
        },
    }


def _symbol_variants(ticker: str) -> list[str]:
    sym = ticker.upper().strip()
    base = nse_code(sym) or sym
    variants: list[str] = []
    if is_india_symbol(sym):
        if sym.endswith(".BO") or sym.endswith(".BSE"):
            variants.extend([f"{base}.NS", sym, f"{base}.BO", base])
        else:
            variants.extend([sym, f"{base}.NS", f"{base}.BO", base])
    else:
        variants.append(sym)
        if "." not in sym:
            variants.extend([f"{sym}.NS", f"{sym}.BO"])
        else:
            variants.append(base)
    seen: set[str] = set()
    out: list[str] = []
    for v in variants:
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


async def _yahoo_quote_summary(http: HttpClient, symbol: str, crumb: str | None) -> dict[str, Any] | None:
    params: dict[str, Any] = {
        "modules": "price,summaryDetail,defaultKeyStatistics,summaryProfile,financialData",
    }
    if crumb:
        params["crumb"] = crumb
    data = await http.get_json(
        f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{quote(symbol)}",
        params=params,
        headers=YAHOO_HEADERS,
        retries=1,
        timeout=10.0,
    )
    result = ((data or {}).get("quoteSummary") or {}).get("result") or []
    return result[0] if result else None


async def _yahoo_v7(http: HttpClient, symbol: str) -> dict[str, Any] | None:
    for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
        try:
            data = await http.get_json(
                f"https://{host}/v7/finance/quote",
                params={"symbols": symbol},
                headers=YAHOO_HEADERS,
                retries=1,
                timeout=10.0,
            )
            rows = ((data or {}).get("quoteResponse") or {}).get("result") or []
            if rows:
                return _quote_from_v7(rows[0])
        except Exception:
            continue
    return None


async def _yahoo_chart(http: HttpClient, symbol: str) -> dict[str, Any] | None:
    try:
        data = await http.get_json(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol)}",
            params={"interval": "1d", "range": "1y"},
            headers=YAHOO_HEADERS,
            retries=1,
            timeout=10.0,
        )
        result = ((data or {}).get("chart") or {}).get("result") or []
        if not result:
            return None
        meta = result[0].get("meta") or {}
        return _quote_from_v7(
            {
                "longName": meta.get("longName") or meta.get("shortName") or symbol,
                "shortName": meta.get("shortName") or symbol,
                "fullExchangeName": meta.get("exchangeName") or meta.get("fullExchangeName"),
                "exchange": meta.get("exchangeName"),
                "currency": meta.get("currency"),
                "regularMarketPrice": meta.get("regularMarketPrice"),
                "fiftyTwoWeekHigh": meta.get("fiftyTwoWeekHigh"),
                "fiftyTwoWeekLow": meta.get("fiftyTwoWeekLow"),
                "marketCap": None,
            }
        )
    except Exception:
        return None


async def _yahoo_crumb(http: HttpClient) -> str | None:
    try:
        await http.get_text("https://fc.yahoo.com", headers=YAHOO_HEADERS, retries=1, timeout=6.0)
        crumb = await http.get_text(
            "https://query1.finance.yahoo.com/v1/test/getcrumb",
            headers=YAHOO_HEADERS,
            retries=1,
            timeout=6.0,
        )
        text = (crumb or "").strip().strip('"')
        if text and "html" not in text.lower() and len(text) < 80:
            return text
    except Exception:
        return None
    return None


async def fetch_yahoo_quote(http: HttpClient, ctx: CompanyContext) -> SourceResult:
    if not ctx.ticker:
        return SourceResult("yahoo", False, error="missing_ticker")
    ordered = _symbol_variants(ctx.ticker)
    last_err = "empty_quote"
    crumb: str | None = None
    crumb_tried = False
    for symbol in ordered:
        cached = get_cached("yahoo_quote", symbol, 6 * 3600)
        if cached is not None:
            return SourceResult("yahoo", True, data=cached)
        quote_obj = None
        try:
            quote_obj = await _yahoo_quote_summary(http, symbol, None)
        except Exception as exc:
            last_err = sanitize_error(exc)
            if last_err == "http_401" and not crumb_tried:
                crumb_tried = True
                crumb = await _yahoo_crumb(http)
            if crumb:
                try:
                    quote_obj = await _yahoo_quote_summary(http, symbol, crumb)
                except Exception as exc2:
                    last_err = sanitize_error(exc2)
        if not quote_obj:
            quote_obj = await _yahoo_v7(http, symbol)
        if not quote_obj:
            quote_obj = await _yahoo_chart(http, symbol)
        if not quote_obj:
            continue
        payload = {"symbol": symbol, "quote": quote_obj}
        set_cached("yahoo_quote", symbol, payload)
        return SourceResult("yahoo", True, data=payload)
    return SourceResult("yahoo", False, error=last_err)


def map_yahoo_financials(quote: dict[str, Any]) -> dict[str, Any]:
    price = quote.get("price") or {}
    detail = quote.get("summaryDetail") or {}
    stats = quote.get("defaultKeyStatistics") or {}
    fin = quote.get("financialData") or {}
    return {
        "market_cap": _raw(price, "marketCap") or _raw(detail, "marketCap"),
        "enterprise_value": _raw(stats, "enterpriseValue"),
        "pe_ratio": _raw(detail, "trailingPE") or _raw(fin, "trailingPE"),
        "eps": _raw(stats, "trailingEps"),
        "beta": _raw(detail, "beta") or _raw(stats, "beta"),
        "week_52_high": _raw(detail, "fiftyTwoWeekHigh"),
        "week_52_low": _raw(detail, "fiftyTwoWeekLow"),
        "dividend_yield": _raw(detail, "dividendYield"),
        "revenue": _raw(fin, "totalRevenue"),
        "profit_margin": _raw(fin, "profitMargins"),
        "ebitda": _raw(fin, "ebitda"),
        "shares_outstanding": _raw(stats, "sharesOutstanding"),
        "currency": price.get("currency") or detail.get("currency"),
    }


def map_yahoo_overview(quote: dict[str, Any]) -> dict[str, Any]:
    profile = quote.get("summaryProfile") or {}
    price = quote.get("price") or {}
    city = profile.get("city")
    country = profile.get("country")
    hq_parts = [x for x in [profile.get("address1"), city, profile.get("state"), country] if x]
    return {
        "name": price.get("longName") or price.get("shortName"),
        "exchange": (price.get("exchangeName") or price.get("exchange")),
        "industry": profile.get("industry"),
        "sector": profile.get("sector"),
        "website": profile.get("website"),
        "employees": profile.get("fullTimeEmployees"),
        "country": country,
        "city": city,
        "address": ", ".join(hq_parts) or None,
        "description": profile.get("longBusinessSummary"),
        "phone": profile.get("phone"),
        "currency": price.get("currency"),
    }
