from __future__ import annotations

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
    items: list[dict] = []
    used_feed: str | None = None
    for feed_url in candidate_feeds(ctx.domain, ctx.website)[:12]:
        try:
            text = await http.get_text(feed_url, headers={"User-Agent": "company-intel-cli/1.0"})
            parsed = feedparser.parse(text)
            if not parsed.entries:
                continue
            used_feed = feed_url
            for entry in parsed.entries[:20]:
                items.append(
                    {
                        "title": getattr(entry, "title", None),
                        "summary": getattr(entry, "summary", None),
                        "url": normalize_url(getattr(entry, "link", None)),
                        "published_at": getattr(entry, "published", None) or getattr(entry, "updated", None),
                        "feed_url": feed_url,
                    }
                )
            break
        except Exception:
            continue
    if not items:
        return SourceResult("rss", False, error="no_feed_found")
    data = {"feed_url": used_feed, "items": items}
    set_cached("rss", cache_key, data)
    return SourceResult("rss", True, data=data)
