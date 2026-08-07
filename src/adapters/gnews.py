from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from src.adapters import CompanyContext, SourceResult
from src.cache import normalize_url
from src.http import HttpClient, sanitize_error


async def fetch_gnews(http: HttpClient, ctx: CompanyContext, lookback_days: int = 3) -> SourceResult:
    key = os.getenv("GNEWS_API_KEY", "").strip()
    if not key:
        return SourceResult("gnews", False, error="missing_api_key")
    q = (ctx.name or ctx.query or "").replace(".", "").strip()
    try:
        data = await http.get_json(
            "https://gnews.io/api/v4/search",
            params={
                "q": q or ctx.query,
                "lang": "en",
                "max": 25,
                "apikey": key,
            },
        )
        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        articles = []
        for a in data.get("articles") or []:
            published = a.get("publishedAt")
            if published:
                try:
                    ts = datetime.fromisoformat(published.replace("Z", "+00:00"))
                    if ts < cutoff:
                        continue
                except Exception:
                    pass
            articles.append(
                {
                    "title": a.get("title"),
                    "summary": a.get("description"),
                    "content": None,
                    "url": normalize_url(a.get("url")),
                    "source_name": (a.get("source") or {}).get("name"),
                    "published_at": published,
                    "via": ["gnews"],
                }
            )
        return SourceResult("gnews", True, data={"articles": articles, "raw": data})
    except Exception as exc:
        return SourceResult("gnews", False, error=sanitize_error(exc))
