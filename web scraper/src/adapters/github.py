from __future__ import annotations

import os

from src.adapters import CompanyContext, SourceResult
from src.cache import get_cached, set_cached
from src.http import HttpClient, sanitize_error


async def fetch_github(http: HttpClient, ctx: CompanyContext) -> SourceResult:
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if not token:
        return SourceResult("github", False, error="missing_api_key")
    q = ctx.name or ctx.query
    cache_key = (ctx.domain or q).lower()
    cached = get_cached("github", cache_key, 86400)
    if cached is not None:
        return SourceResult("github", True, data=cached)
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "company-intel-cli",
    }
    try:
        search_q = f"{q} in:login in:name type:org"
        if ctx.domain:
            search_q = f"{q} {ctx.domain}"
        search = await http.get_json(
            "https://api.github.com/search/users",
            params={"q": search_q, "per_page": 5},
            headers=headers,
            retries=2,
            timeout=8.0,
        )
        items = search.get("items") or []
        org = None
        for item in items:
            if item.get("type") == "Organization" or True:
                login = item.get("login")
                if not login:
                    continue
                org = await http.get_json(
                    f"https://api.github.com/users/{login}",
                    headers=headers,
                    retries=2,
                    timeout=8.0,
                )
                repos = await http.get_json(
                    f"https://api.github.com/users/{login}/repos",
                    params={"sort": "stars", "per_page": 10, "type": "public"},
                    headers=headers,
                    retries=2,
                    timeout=8.0,
                )
                data = {"org": org, "repos": repos, "search": search}
                set_cached("github", cache_key, data)
                return SourceResult("github", True, data=data)
        return SourceResult("github", False, error="no_org_match")
    except Exception as exc:
        return SourceResult("github", False, error=sanitize_error(exc))
