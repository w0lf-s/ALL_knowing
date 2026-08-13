from __future__ import annotations

import os
from typing import Any

from src.adapters import CompanyContext, SourceResult
from src.cache import get_cached, set_cached
from src.http import HttpClient, sanitize_error
from src.rate_limit import RateLimits


def _symbol_variants(ticker: str) -> list[str]:
    sym = ticker.upper().strip()
    out = [sym]
    if "." in sym:
        base = sym.split(".", 1)[0]
        if base and base not in out:
            out.append(base)
    return out


def _num(v: Any) -> float | None:
    if v is None or v == "None" or v == "-":
        return None
    try:
        return float(v)
    except Exception:
        return None


async def search_symbol(http: HttpClient, query: str) -> SourceResult:
    key = os.getenv("ALPHA_VANTAGE_API_KEY", "").strip()
    if not key:
        return SourceResult("alpha_vantage", False, error="missing_api_key")
    cached = get_cached("av_search", query.lower(), 86400)
    if cached is not None:
        return SourceResult("alpha_vantage", True, data={"search": cached, "cached": True})
    try:
        data = await http.get_json(
            "https://www.alphavantage.co/query",
            params={"function": "SYMBOL_SEARCH", "keywords": query, "apikey": key},
            retries=2,
            timeout=10.0,
        )
        if isinstance(data, dict) and (data.get("Note") or data.get("Information")):
            return SourceResult("alpha_vantage", False, error="rate_limited")
        matches = (data or {}).get("bestMatches") or []
        set_cached("av_search", query.lower(), matches)
        return SourceResult("alpha_vantage", True, data={"search": matches})
    except Exception as exc:
        return SourceResult("alpha_vantage", False, error=sanitize_error(exc))


def pick_av_symbol(matches: list[dict], query: str) -> tuple[str | None, str | None]:
    if not matches:
        return None, None
    q_lower = query.strip().lower()
    best: tuple[int, str, str | None] | None = None
    for item in matches:
        sym = (item.get("1. symbol") or item.get("symbol") or "").upper().strip()
        name = item.get("2. name") or item.get("name")
        region = (item.get("4. region") or item.get("region") or "").lower()
        if not sym:
            continue
        score = 0
        if name and q_lower in str(name).lower():
            score += 40
        if "united states" in region:
            score += 20
        if "india" in region:
            score += 25
        if sym.endswith(".BSE") or sym.endswith(".NSE") or sym.endswith(".NS") or sym.endswith(".BO"):
            score += 15
        if best is None or score > best[0]:
            best = (score, sym, name)
    if best:
        return best[1], best[2]
    first = matches[0]
    return (
        (first.get("1. symbol") or "").upper() or None,
        first.get("2. name"),
    )


async def fetch_overview(
    http: HttpClient,
    limits: RateLimits,
    ctx: CompanyContext,
) -> SourceResult:
    key = os.getenv("ALPHA_VANTAGE_API_KEY", "").strip()
    if not key:
        return SourceResult("alpha_vantage", False, error="missing_api_key")
    if not ctx.ticker:
        return SourceResult("alpha_vantage", False, error="missing_ticker")
    cached = get_cached("alpha_vantage", ctx.ticker.upper(), 7 * 86400)
    if cached is not None:
        return SourceResult("alpha_vantage", True, data=cached)
    soft = int(os.getenv("AV_DAILY_SOFT_CAP", "20"))
    allowed = await limits.alpha_vantage_slot(soft)
    if not allowed:
        return SourceResult("alpha_vantage", False, error="daily_soft_cap")
    last_err = "empty_overview"
    try:
        for symbol in _symbol_variants(ctx.ticker):
            data = await http.get_json(
                "https://www.alphavantage.co/query",
                params={"function": "OVERVIEW", "symbol": symbol, "apikey": key},
            )
            if isinstance(data, dict) and data.get("Note"):
                return SourceResult("alpha_vantage", False, error="rate_limited")
            if isinstance(data, dict) and data.get("Information"):
                return SourceResult("alpha_vantage", False, error="provider_message")
            if not data or (isinstance(data, dict) and not data.get("Symbol")):
                last_err = "empty_overview"
                continue
            set_cached("alpha_vantage", ctx.ticker.upper(), data)
            return SourceResult("alpha_vantage", True, data=data)
        return SourceResult("alpha_vantage", False, error=last_err)
    except Exception as exc:
        return SourceResult("alpha_vantage", False, error=sanitize_error(exc))


def map_overview_financials(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "market_cap": data.get("MarketCapitalization"),
        "enterprise_value": None,
        "ebitda": _num(data.get("EBITDA")),
        "pe_ratio": _num(data.get("PERatio")),
        "peg_ratio": _num(data.get("PEGRatio")),
        "book_value": _num(data.get("BookValue")),
        "dividend_per_share": _num(data.get("DividendPerShare")),
        "dividend_yield": _num(data.get("DividendYield")),
        "eps": _num(data.get("EPS")),
        "diluted_eps_ttm": _num(data.get("DilutedEPSTTM")),
        "revenue_ttm": _num(data.get("RevenueTTM")),
        "revenue_per_share_ttm": _num(data.get("RevenuePerShareTTM")),
        "profit_margin": _num(data.get("ProfitMargin")),
        "operating_margin_ttm": _num(data.get("OperatingMarginTTM")),
        "return_on_assets_ttm": _num(data.get("ReturnOnAssetsTTM")),
        "return_on_equity_ttm": _num(data.get("ReturnOnEquityTTM")),
        "gross_profit": _num(data.get("GrossProfitTTM")),
        "quarterly_earnings_growth_yoy": _num(data.get("QuarterlyEarningsGrowthYOY")),
        "quarterly_revenue_growth_yoy": _num(data.get("QuarterlyRevenueGrowthYOY")),
        "analyst_target_price": _num(data.get("AnalystTargetPrice")),
        "trailing_pe": _num(data.get("TrailingPE")),
        "forward_pe": _num(data.get("ForwardPE")),
        "price_to_sales_ttm": _num(data.get("PriceToSalesRatioTTM")),
        "price_to_book": _num(data.get("PriceToBookRatio")),
        "ev_to_revenue": _num(data.get("EVToRevenue")),
        "ev_to_ebitda": _num(data.get("EVToEBITDA")),
        "beta": _num(data.get("Beta")),
        "week_52_high": _num(data.get("52WeekHigh")),
        "week_52_low": _num(data.get("52WeekLow")),
        "moving_average_50": _num(data.get("50DayMovingAverage")),
        "moving_average_200": _num(data.get("200DayMovingAverage")),
        "shares_outstanding": _num(data.get("SharesOutstanding")),
        "shares_float": _num(data.get("SharesFloat")),
        "percent_insiders": _num(data.get("PercentInsiders")),
        "percent_institutions": _num(data.get("PercentInstitutions")),
        "dividend_date": data.get("DividendDate") or None,
        "ex_dividend_date": data.get("ExDividendDate") or None,
        "revenue": data.get("RevenueTTM"),
    }
