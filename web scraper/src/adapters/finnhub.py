from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

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


async def search_symbol(http: HttpClient, limits: RateLimits, query: str) -> SourceResult:
    key = os.getenv("FINNHUB_API_KEY", "").strip()
    if not key:
        return SourceResult("finnhub", False, error="missing_api_key")
    cached = get_cached("finnhub_search", query.lower(), 86400)
    if cached is not None:
        return SourceResult("finnhub", True, data={"search": cached, "cached": True})
    try:
        await limits.finnhub.acquire()
        data = await http.get_json(
            "https://finnhub.io/api/v1/search",
            params={"q": query, "token": key},
        )
        set_cached("finnhub_search", query.lower(), data)
        return SourceResult("finnhub", True, data={"search": data})
    except Exception as exc:
        return SourceResult("finnhub", False, error=sanitize_error(exc))


async def fetch_profile_metrics(
    http: HttpClient,
    limits: RateLimits,
    ctx: CompanyContext,
) -> SourceResult:
    key = os.getenv("FINNHUB_API_KEY", "").strip()
    if not key:
        return SourceResult("finnhub", False, error="missing_api_key")
    if not ctx.ticker:
        return SourceResult("finnhub", False, error="missing_ticker")
    cached = get_cached("finnhub_profile", ctx.ticker.upper(), 86400)
    if cached is not None:
        return SourceResult("finnhub", True, data=cached)
    last_err = "request_failed"
    for symbol in _symbol_variants(ctx.ticker):
        try:
            await limits.finnhub.acquire()
            profile = await http.get_json(
                "https://finnhub.io/api/v1/stock/profile2",
                params={"symbol": symbol, "token": key},
            )
            if not isinstance(profile, dict) or not profile:
                last_err = "empty_profile"
                continue
            await limits.finnhub.acquire()
            metrics = await http.get_json(
                "https://finnhub.io/api/v1/stock/metric",
                params={"symbol": symbol, "metric": "all", "token": key},
            )
            data = {"profile": profile, "metrics": metrics, "symbol_used": symbol}
            set_cached("finnhub_profile", ctx.ticker.upper(), data)
            return SourceResult("finnhub", True, data=data)
        except Exception as exc:
            last_err = sanitize_error(exc)
            continue
    return SourceResult("finnhub", False, error=last_err)


def pick_best_symbol(search: dict[str, Any], query: str) -> tuple[str | None, str | None]:
    import re

    results = search.get("result") or []
    if not results:
        return None, None
    q = query.strip()
    q_upper = q.upper()
    q_lower = q.lower()
    penalty_suffixes = {
        ".DE",
        ".F",
        ".DU",
        ".MU",
        ".HM",
        ".SG",
        ".TG",
        ".BE",
        ".HA",
        ".STU",
    }
    preferred_suffixes = {
        "": 30,
        ".US": 30,
        ".NS": 28,
        ".BO": 26,
        ".L": 18,
        ".TO": 16,
        ".HK": 16,
        ".T": 14,
        ".AX": 12,
        ".NY": 20,
    }

    best: tuple[int, str, str | None] | None = None
    for item in results:
        sym = (item.get("symbol") or "").upper().strip()
        if not sym:
            continue
        desc = (item.get("description") or "").strip()
        desc_l = desc.lower()
        typ = (item.get("type") or "").lower()
        if typ and typ not in ("common stock", "eqs", "equity", ""):
            continue

        if "." in sym:
            base, suffix = sym.split(".", 1)
            suffix = "." + suffix
        else:
            base, suffix = sym, ""

        score = 0
        if sym == q_upper:
            score += 70
        if base == q_upper:
            score += 35
        if re.match(rf"^{re.escape(q_lower)}(\b|$)", desc_l):
            score += 100
        elif re.search(rf"\b{re.escape(q_lower)}\b", desc_l):
            score += 25

        if suffix in penalty_suffixes:
            score -= 60
        else:
            score += preferred_suffixes.get(suffix, -5)

        if len(q_upper) <= 5 and base.startswith(q_upper) and len(base) > len(q_upper):
            if re.match(rf"^{re.escape(q_lower)}(\b|$)", desc_l):
                score += 40

        if best is None or score > best[0]:
            best = (score, sym, item.get("description"))

    if best and best[0] > 0:
        return best[1], best[2]

    for item in results:
        sym = (item.get("symbol") or "").upper()
        desc_l = (item.get("description") or "").lower()
        if re.match(rf"^{re.escape(q_lower)}(\b|$)", desc_l):
            return sym or None, item.get("description")

    first = results[0]
    return (first.get("symbol") or "").upper() or None, first.get("description")


def domain_from_web(url: str | None) -> str | None:
    if not url:
        return None
    raw = url if "://" in url else f"https://{url}"
    try:
        host = urlparse(raw).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return host or None
    except Exception:
        return None
