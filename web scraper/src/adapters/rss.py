from __future__ import annotations

import asyncio
from urllib.parse import urljoin

import feedparser

from src.adapters import CompanyContext, SourceResult
from src.cache import get_cached, normalize_url, set_cached
from src.http import HttpClient


def candidate_feeds(domain: str | None, website: str | None) -> list[str]:
    bases: list[str] = []
    if website:
        base = website if website.startswith("http") else f"https://{website}"
        bases.append(base.rstrip("/") + "/")
    if domain:
        bases.append(f"https://{domain}/")
        bases.append(f"https://www.{domain}/")
    paths = [
        "feed",
        "rss",
        "rss.xml",
        "feed.xml",
        "atom.xml",
        "news/rss",
        "newsroom/rss",
        "press/rss",
        "investor/rss",
        "blog/feed",
        "blog/rss",
    ]
    urls: list[str] = []
    seen: set[str] = set()
    for base in bases:
        for p in paths:
            u = urljoin(base, p)
            if u not in seen:
                seen.add(u)
                urls.append(u)
    return urls


async def fetch_rss(http: HttpClient, ctx: CompanyContext) -> SourceResult:
    if not ctx.domain and not ctx.website:
        return SourceResult("rss", False, error="missing_domain")
    cache_key = (ctx.domain or ctx.website or ctx.query).lower()
    cached = get_cached("rss", cache_key, 6 * 3600)
    if cached is not None:
        return SourceResult("rss", True, data=cached)

    async def probe(feed_url: str):
        try:
            text = await http.get_text(
                feed_url,
                headers={"User-Agent": "company-intel-cli/1.0"},
                retries=1,
                timeout=5.0,
            )
            parsed = feedparser.parse(text)
            if not parsed.entries:
                return None
            items = []
            for entry in parsed.entries[:20]:
                items.append(
                    {
                        "title": getattr(entry, "title", None),
                        "summary": getattr(entry, "summary", None),
                        "url": normalize_url(getattr(entry, "link", None)),
                        "published_at": getattr(entry, "published", None)
                        or getattr(entry, "updated", None),
                        "feed_url": feed_url,
                    }
                )
            return {"feed_url": feed_url, "items": items}
        except Exception:
            return None

    feeds = candidate_feeds(ctx.domain, ctx.website)[:6]
    results = await asyncio.gather(*[probe(u) for u in feeds])
    hit = next((r for r in results if r and r.get("items")), None)
    if not hit:
        return SourceResult("rss", False, error="no_feed_found")
    set_cached("rss", cache_key, hit)
    return SourceResult("rss", True, data=hit)
