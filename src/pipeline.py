from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv

from src.adapters import SourceResult
from src.adapters.alpha_vantage import fetch_overview
from src.adapters.finnhub import domain_from_web, fetch_profile_metrics
from src.adapters.github import fetch_github
from src.adapters.gnews import fetch_gnews
from src.adapters.newsapi import fetch_newsapi
from src.adapters.rss import fetch_rss
from src.adapters.sec_edgar import fetch_filings
from src.adapters.wikipedia import fetch_wikipedia
from src.arrange_text import arrange_text
from src.cache import load_news_day, save_news_day
from src.http import HttpClient
from src.merge import is_english_article, merge_dossier, merge_news_articles
from src.news_enrich import enrich_articles, needs_content, pick_best_articles
from src.news_relevance import filter_relevant_articles
from src.paths import COMPANY_DIR, LASTRUN, RAW_DIR, company_key, ensure_dirs
from src.rate_limit import RateLimits
from src.resolve import resolve_identity
from src.schema import CompanyDossier


def _write_json(path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


async def run_pipeline(
    query: str,
    *,
    use_groq: bool = True,
    use_playwright: bool = True,
) -> CompanyDossier:
    load_dotenv()
    ensure_dirs()
    key = company_key(query)
    lookback = int(os.getenv("NEWS_LOOKBACK_DAYS", "3"))
    generated_at = datetime.now(timezone.utc).isoformat()

    http = HttpClient()
    limits = RateLimits()
    sources: dict[str, SourceResult] = {}

    try:
        ctx = await resolve_identity(http, limits, query)

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

        wiki_task = fetch_wikipedia(http, ctx)
        sec_task = fetch_filings(http, limits, ctx)
        gh_task = fetch_github(http, ctx)
        rss_task = fetch_rss(http, ctx)

        wiki, sec, gh, rss = await asyncio.gather(wiki_task, sec_task, gh_task, rss_task)
        sources["wikipedia"] = wiki
        sources["sec_edgar"] = sec
        sources["github"] = gh
        sources["rss"] = rss

        if wiki.ok and isinstance(wiki.data, dict) and wiki.data.get("title"):
            ctx.wiki_title = wiki.data.get("title")

        av = await fetch_overview(http, limits, ctx)
        sources["alpha_vantage"] = av
        if av.ok and isinstance(av.data, dict):
            if av.data.get("Website") and not ctx.website:
                ctx.website = av.data.get("Website")
                ctx.domain = domain_from_web(ctx.website)
            if av.data.get("Name"):
                ctx.name = av.data.get("Name")

        news_cached = load_news_day(key)
        articles: list[dict[str, Any]] = []
        company_label = ctx.name or query
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
                enriched = await enrich_articles(relevant, top_n=8, enabled=True)
                articles = pick_best_articles(
                    [a for a in enriched if is_english_article(a)],
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
            enriched = await enrich_articles(relevant, top_n=8, enabled=use_playwright)
            articles = pick_best_articles(
                [a for a in enriched if is_english_article(a)],
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

        company_path = COMPANY_DIR / f"{key}.json"
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

        dossier = CompanyDossier.model_validate(dossier.model_dump())
        payload = dossier.model_dump()
        _write_json(company_path, payload)
        _write_json(LASTRUN, payload)
        return dossier
    finally:
        await http.aclose()
