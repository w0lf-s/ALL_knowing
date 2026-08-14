from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

_ENV = Path(__file__).resolve().parent.parent.parent / "not to share" / ".env"
load_dotenv(_ENV if _ENV.exists() else None)

from src.adapters import SourceResult
from src.adapters.alpha_vantage import fetch_overview
from src.adapters.finnhub import domain_from_web, fetch_profile_metrics
from src.adapters.github import fetch_github
from src.adapters.gnews import fetch_gnews
from src.adapters.newsapi import fetch_newsapi
from src.adapters.nse import fetch_nse_announcements
from src.adapters.rss import fetch_rss
from src.adapters.sec_edgar import fetch_filings
from src.adapters.wikipedia import fetch_wikipedia
from src.adapters.yahoo import fetch_yahoo_quote, is_india_symbol
from src.arrange_text import arrange_text
from src.cache import load_news_day, save_news_day
from src.http import HttpClient
from src.merge import is_english_article, merge_dossier, merge_news_articles
from src.news_enrich import enrich_articles, is_error_article, needs_content, pick_best_articles
from src.news_relevance import filter_relevant_articles
from src.paths import COMPANY_DIR, LASTRUN, RAW_DIR, company_key, ensure_dirs
from src.rate_limit import RateLimits
from src.resolve import resolve_identity
from src.schema import CompanyDossier


def _write_json(path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


_progress_callback = None


def set_progress_callback(cb):
    global _progress_callback
    _progress_callback = cb


def _emit(pct: int, step: str):
    if _progress_callback:
        _progress_callback(pct, step)


async def run_pipeline(
    query: str,
    *,
    use_groq: bool = True,
    use_playwright: bool = True,
    skip_news: bool = False,
    lite: bool = False,
) -> CompanyDossier:
    ensure_dirs()
    key = company_key(query)
    lookback = int(os.getenv("NEWS_LOOKBACK_DAYS", "3"))
    generated_at = datetime.now(timezone.utc).isoformat()

    http = HttpClient()
    limits = RateLimits()
    sources: dict[str, SourceResult] = {}

    try:
        _emit(5, "Resolving company identity")
        ctx = await resolve_identity(http, limits, query)
        _emit(15, "Fetching financial profile")

        fh = await fetch_profile_metrics(http, limits, ctx)
        sources["finnhub"] = fh
        if fh.ok and isinstance(fh.data, dict):
            profile = fh.data.get("profile") or {}
            if profile.get("weburl"):
                ctx.website = profile.get("weburl")
                ctx.domain = domain_from_web(ctx.website)
            if profile.get("name"):
                ctx.name = profile.get("name")
            if profile.get("exchange"):
                ctx.exchanges = [profile.get("exchange")]

        _emit(20, "Fetching market data")
        yh = await fetch_yahoo_quote(http, ctx)
        sources["yahoo"] = yh
        if yh.ok and isinstance(yh.data, dict):
            used = yh.data.get("symbol")
            if used:
                ctx.ticker = used
            quote = yh.data.get("quote") or {}
            price = quote.get("price") or {}
            profile = quote.get("summaryProfile") or {}
            if price.get("exchangeName"):
                ctx.exchanges = list(dict.fromkeys((ctx.exchanges or []) + [price.get("exchangeName")]))
            if profile.get("website") and not ctx.website:
                ctx.website = profile.get("website")
                ctx.domain = domain_from_web(ctx.website)
            if price.get("longName"):
                ctx.name = price.get("longName")

        async def _step(coro, pct: int, step: str):
            result = await coro
            _emit(pct, step)
            return result

        _emit(25, "Fetching public records")
        india = is_india_symbol(ctx.ticker)
        if lite:
            wiki = await fetch_wikipedia(http, ctx)
            if india:
                sec = SourceResult("sec_edgar", False, error="india_listing")
                nse = await fetch_nse_announcements(http, ctx)
            else:
                sec = await fetch_filings(http, limits, ctx)
                nse = SourceResult("nse", False, error="us_listing")
            gh = SourceResult("github", False, error="skipped_lite")
            rss = SourceResult("rss", False, error="skipped_lite")
            av = await fetch_overview(http, limits, ctx)
        else:
            if india:
                wiki, nse, gh, rss, av = await asyncio.gather(
                    _step(fetch_wikipedia(http, ctx), 32, "Fetching public records"),
                    _step(fetch_nse_announcements(http, ctx), 36, "Fetching filings"),
                    _step(fetch_github(http, ctx), 40, "Fetching GitHub"),
                    _step(fetch_rss(http, ctx), 42, "Fetching RSS"),
                    _step(fetch_overview(http, limits, ctx), 50, "Fetching market data"),
                )
                sec = SourceResult("sec_edgar", False, error="india_listing")
            else:
                wiki, sec, nse, gh, rss, av = await asyncio.gather(
                    _step(fetch_wikipedia(http, ctx), 32, "Fetching public records"),
                    _step(fetch_filings(http, limits, ctx), 36, "Fetching filings"),
                    _step(fetch_nse_announcements(http, ctx), 38, "Fetching NSE filings"),
                    _step(fetch_github(http, ctx), 40, "Fetching GitHub"),
                    _step(fetch_rss(http, ctx), 42, "Fetching RSS"),
                    _step(fetch_overview(http, limits, ctx), 50, "Fetching market data"),
                )
        sources["wikipedia"] = wiki
        sources["sec_edgar"] = sec
        sources["nse"] = nse
        sources["github"] = gh
        sources["rss"] = rss
        sources["alpha_vantage"] = av

        if wiki.ok and isinstance(wiki.data, dict) and wiki.data.get("title"):
            ctx.wiki_title = wiki.data.get("title")

        _emit(55, "Fetching news articles")
        if av.ok and isinstance(av.data, dict):
            if av.data.get("Website") and not ctx.website:
                ctx.website = av.data.get("Website")
                ctx.domain = domain_from_web(ctx.website)
            if av.data.get("Name"):
                ctx.name = av.data.get("Name")

        articles: list[dict[str, Any]] = []
        company_label = ctx.name or query
        if lite or skip_news:
            sources["newsapi"] = SourceResult("newsapi", False, error="skipped")
            sources["gnews"] = SourceResult("gnews", False, error="skipped")
        else:
            news_cached = load_news_day(key)
            if news_cached and isinstance(news_cached.get("articles"), list) and news_cached["articles"]:
                cached = [a for a in news_cached["articles"] if is_english_article(a)]
                sources["newsapi"] = SourceResult("newsapi", True, data={"cached": True})
                sources["gnews"] = SourceResult("gnews", True, data={"cached": True})
                if use_playwright and needs_content(cached):
                    relevant = filter_relevant_articles(
                        cached,
                        company_name=company_label,
                        ticker=ctx.ticker,
                        query=query,
                        limit=8,
                        use_groq=use_groq,
                    )
                    _emit(70, "Opening articles")
                    enriched = await enrich_articles(relevant, top_n=8, enabled=True)
                    articles = pick_best_articles(
                        [a for a in enriched if is_english_article(a) and not is_error_article(a)],
                        limit=8,
                    )
                else:
                    articles = pick_best_articles(cached, limit=8)
                save_news_day(
                    key,
                    {
                        "query": query,
                        "lookback_days": lookback,
                        "articles": articles,
                        "fetched_at": generated_at,
                    },
                )
            else:
                n_api, n_g = await asyncio.gather(
                    fetch_newsapi(http, ctx, lookback),
                    fetch_gnews(http, ctx, lookback),
                )
                sources["newsapi"] = n_api
                sources["gnews"] = n_g
                batches = []
                if n_api.ok and isinstance(n_api.data, dict):
                    batches.append(n_api.data.get("articles") or [])
                if n_g.ok and isinstance(n_g.data, dict):
                    batches.append(n_g.data.get("articles") or [])
                candidates = merge_news_articles(batches, limit=30)
                relevant = filter_relevant_articles(
                    candidates,
                    company_name=company_label,
                    ticker=ctx.ticker,
                    query=query,
                    limit=8,
                    use_groq=use_groq,
                )
                _emit(70, "Opening articles")
                enriched = await enrich_articles(relevant, top_n=8, enabled=use_playwright)
                articles = pick_best_articles(
                    [a for a in enriched if is_english_article(a) and not is_error_article(a)],
                    limit=8,
                )
                save_news_day(
                    key,
                    {
                        "query": query,
                        "lookback_days": lookback,
                        "articles": articles,
                        "fetched_at": generated_at,
                    },
                )

        _emit(80, "Building company dossier")
        raw_path = RAW_DIR / f"{key}.json"
        raw_bundle = {
            "query": query,
            "resolved": {
                "ticker": ctx.ticker,
                "cik": ctx.cik,
                "name": ctx.name,
                "website": ctx.website,
                "wiki_title": ctx.wiki_title,
                "domain": ctx.domain,
            },
            "sources": {
                name: {"ok": sr.ok, "error": sr.error, "data": sr.data}
                for name, sr in sources.items()
            },
            "news_articles": articles,
            "fetched_at": generated_at,
        }
        _write_json(raw_path, raw_bundle)

        _emit(90, "Merging and saving results")
        company_path = COMPANY_DIR / f"{key}.json"
        prev_news = None
        if (lite or skip_news) and company_path.exists():
            try:
                prev = json.loads(company_path.read_text(encoding="utf-8"))
                if isinstance(prev.get("news"), dict):
                    prev_news = prev["news"]
            except Exception:
                prev_news = None
        dossier = merge_dossier(
            query,
            ctx,
            sources,
            news_articles=articles,
            lookback_days=lookback,
            generated_at=generated_at,
            raw_path=str(raw_path),
            company_path=str(company_path),
        )

        if use_groq:
            dossier = arrange_text(dossier)

        _emit(95, "Validating data")
        dossier = CompanyDossier.model_validate(dossier.model_dump())
        payload = dossier.model_dump()
        if lite or skip_news:
            save_payload = dict(payload)
            if prev_news:
                save_payload["news"] = prev_news
            payload["news"] = {"digest_summary": None, "lookback_days": lookback, "articles": []}
            _write_json(company_path, save_payload)
            _write_json(LASTRUN, save_payload)
            _emit(100, "Complete")
            return CompanyDossier.model_validate(payload)
        _write_json(company_path, payload)
        _write_json(LASTRUN, payload)
        _emit(100, "Complete")
        return dossier
    finally:
        await http.aclose()


async def fetch_company_news(
    query: str,
    *,
    use_groq: bool = True,
    use_playwright: bool = True,
) -> dict[str, Any]:
    ensure_dirs()
    lookback = int(os.getenv("NEWS_LOOKBACK_DAYS", "3"))
    http = HttpClient()
    limits = RateLimits()
    try:
        ctx = await resolve_identity(http, limits, query)
        company_label = ctx.name or query
        n_api, n_g = await asyncio.gather(
            fetch_newsapi(http, ctx, lookback),
            fetch_gnews(http, ctx, lookback),
        )
        batches = []
        if n_api.ok and isinstance(n_api.data, dict):
            batches.append(n_api.data.get("articles") or [])
        if n_g.ok and isinstance(n_g.data, dict):
            batches.append(n_g.data.get("articles") or [])
        candidates = merge_news_articles(batches, limit=30)
        relevant = filter_relevant_articles(
            candidates,
            company_name=company_label,
            ticker=ctx.ticker,
            query=query,
            limit=8,
            use_groq=use_groq,
        )
        enriched = await enrich_articles(relevant, top_n=8, enabled=use_playwright)
        articles = pick_best_articles(
            [a for a in enriched if is_english_article(a) and not is_error_article(a)],
            limit=8,
        )
        generated_at = datetime.now(timezone.utc).isoformat()
        save_news_day(
            company_key(query),
            {
                "query": query,
                "lookback_days": lookback,
                "articles": articles,
                "fetched_at": generated_at,
            },
        )
        return {
            "query": query,
            "name": company_label,
            "ticker": ctx.ticker,
            "articles": articles,
            "lookback_days": lookback,
        }
    finally:
        await http.aclose()
