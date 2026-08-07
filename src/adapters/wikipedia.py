from __future__ import annotations

import re
from urllib.parse import quote

from rapidfuzz import fuzz

from src.adapters import CompanyContext, SourceResult
from src.cache import get_cached, set_cached
from src.http import HttpClient, sanitize_error


WIKI_HEADERS = {
    "User-Agent": "AllKnowingCompanySearch/1.0 (educational research; contact@example.com)",
    "Accept": "application/json",
}

_LEGAL_SUFFIX = re.compile(
    r"\b(ltd|limited|inc|incorporated|corp|corporation|plc|llc|co|company)\.?$",
    re.I,
)


def _strip_legal(name: str) -> str:
    out = name.strip()
    while True:
        nxt = _LEGAL_SUFFIX.sub("", out).rstrip(" ,.").strip()
        if nxt == out:
            return out
        out = nxt


def _search_candidates(ctx: CompanyContext) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []

    def add(raw: str | None) -> None:
        if not raw:
            return
        text = " ".join(raw.split()).strip()
        if not text:
            return
        key = text.lower()
        if key not in seen:
            seen.add(key)
            out.append(text)
        cleaned = _strip_legal(text)
        if cleaned and cleaned.lower() not in seen:
            seen.add(cleaned.lower())
            out.append(cleaned)
        words = [w for w in cleaned.split() if w.lower() not in {"and", "the", "of", "for"}]
        if len(words) >= 2:
            short = " ".join(words[:2])
            if short.lower() not in seen:
                seen.add(short.lower())
                out.append(short)
        if len(words) >= 3:
            mid = " ".join(words[:3])
            if mid.lower() not in seen:
                seen.add(mid.lower())
                out.append(mid)

    add(ctx.query)
    add(ctx.name)
    add(ctx.wiki_title)
    return out


def _pick_title(titles: list[str], target: str) -> str | None:
    if not titles:
        return None
    target_l = target.lower().strip()
    best: tuple[int, str] | None = None
    for title in titles:
        score = fuzz.token_set_ratio(target_l, title.lower())
        if title.lower().startswith(target_l[: min(8, len(target_l))]):
            score += 15
        if best is None or score > best[0]:
            best = (score, title)
    if best and best[0] >= 55:
        return best[1]
    return titles[0]


async def fetch_wikipedia(http: HttpClient, ctx: CompanyContext) -> SourceResult:
    candidates = _search_candidates(ctx)
    if not candidates:
        return SourceResult("wikipedia", False, error="no_match")
    cache_key = (ctx.name or ctx.query).lower()
    cached = get_cached("wikipedia", cache_key, 7 * 86400)
    if cached is not None:
        return SourceResult("wikipedia", True, data=cached)
    target = _strip_legal(ctx.name or ctx.query)
    try:
        chosen_title: str | None = None
        last_search = None
        for q in candidates:
            search = await http.get_json(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action": "opensearch",
                    "search": q,
                    "limit": 5,
                    "namespace": 0,
                    "format": "json",
                },
                headers=WIKI_HEADERS,
            )
            last_search = search
            titles: list[str] = []
            if isinstance(search, list) and len(search) > 1 and search[1]:
                titles = list(search[1])
            picked = _pick_title(titles, target)
            if picked:
                chosen_title = picked
                break
        if not chosen_title:
            return SourceResult("wikipedia", False, error="no_match")
        summary = await http.get_json(
            f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(chosen_title.replace(' ', '_'))}",
            headers=WIKI_HEADERS,
        )
        data = {"title": chosen_title, "summary": summary, "search": last_search}
        set_cached("wikipedia", cache_key, data)
        return SourceResult("wikipedia", True, data=data)
    except Exception as exc:
        return SourceResult("wikipedia", False, error=sanitize_error(exc))
