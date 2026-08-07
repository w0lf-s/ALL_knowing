from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from src.adapters import CompanyContext, SourceResult
from src.cache import normalize_url
from src.http import HttpClient, sanitize_error


async def fetch_newsapi(http: HttpClient, ctx: CompanyContext, lookback_days: int = 3) -> SourceResult:
    key = os.getenv("NEWSAPI_API_KEY", "").strip()
    if not key:
        return SourceResult("newsapi", False, error="missing_api_key")
    q = ctx.name or ctx.query
    if ctx.ticker:
        q = f'"{q}" OR {ctx.ticker}'
    frm = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).date().isoformat()
    try:
        data = await http.get_json(
            "https://newsapi.org/v2/everything",
            params={
                "q": q,
                "from": frm,
                "sortBy": "publishedAt",
                "language": "en",
                "pageSize": 30,
                "apiKey": key,
            },
        )
        articles = []
        for a in data.get("articles") or []:
            articles.append(
                {
                    "title": a.get("title"),
                    "summary": a.get("description"),
                    "content": None,
                    "url": normalize_url(a.get("url")),
                    "source_name": (a.get("source") or {}).get("name"),
                    "published_at": a.get("publishedAt"),
                    "via": ["newsapi"],
                }
            )
        return SourceResult("newsapi", True, data={"articles": articles, "raw": data})
    except Exception as exc:
        return SourceResult("newsapi", False, error=sanitize_error(exc))
