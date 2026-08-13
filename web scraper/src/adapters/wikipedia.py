from __future__ import annotations

import re
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

    add(ctx.wiki_title)
    add(ctx.name)
    add(ctx.query)
    return out


def is_disambiguation(data: dict | None) -> bool:
    if not isinstance(data, dict):
        return False
    summary = data.get("summary") or {}
    if str(summary.get("type") or "").lower() == "disambiguation":
        return True
    extract = str(summary.get("extract") or "")
    if re.search(r"\bmay refer to\b", extract, re.I):
        return True
    desc = str(summary.get("description") or "").lower()
    return "disambiguation" in desc or "same term" in desc


_GENERIC_LEAD = re.compile(r"^an?\s+[\w'-]+\s+is\b", re.I)
_GENERIC_DESC = re.compile(
    r"\b(watercraft|vessel|species|river|given name|surname|film|album|plant|fruit|animal)\b",
    re.I,
)
_COMPANY_TITLE = re.compile(
    r"\((company|brand)\)|\b(inc|ltd|limited|corp|holdings|electronics|lifestyle)\b",
    re.I,
)


def is_generic_topic(data: dict | None, query: str = "") -> bool:
    if not isinstance(data, dict) or not query:
        return False
    title = str(data.get("title") or "").strip().lower()
    q = query.strip().lower()
    if title not in {q, q.rstrip("s")}:
        return False
    summary = data.get("summary") or {}
    extract = str(summary.get("extract") or "").strip()
    if _GENERIC_LEAD.match(extract):
        return True
    desc = str(summary.get("description") or "")
    return bool(_GENERIC_DESC.search(desc))


def search_titles(data: dict | None) -> list[str]:
    if not isinstance(data, dict):
        return []
    search = data.get("search")
    if isinstance(search, list) and len(search) > 1 and isinstance(search[1], list):
        return [str(t).strip() for t in search[1] if str(t).strip()]
    return []


def _pick_title(titles: list[str], target: str) -> str | None:
    if not titles:
        return None
    target_l = target.lower().strip()
    best: tuple[int, str] | None = None
    for title in titles:
        tl = title.lower().strip()
        if "disambiguation" in tl:
            continue
        score = fuzz.token_set_ratio(target_l, tl)
        if tl.startswith(target_l[: min(8, len(target_l))]):
            score += 15
        if _COMPANY_TITLE.search(title):
            score += 35
        if tl == target_l and len(target_l) <= 8:
            score -= 30
        if best is None or score > best[0]:
            best = (score, title)
    if best and best[0] >= 40:
        return best[1]
    usable = [t for t in titles if "disambiguation" not in t.lower()]
    return usable[0] if usable else None


async def fetch_wikipedia(http: HttpClient, ctx: CompanyContext) -> SourceResult:
    candidates = _search_candidates(ctx)
    if not candidates:
        return SourceResult("wikipedia", False, error="no_match")
    keys = []
    for raw in (ctx.query, ctx.name):
        if raw and raw.lower() not in keys:
            keys.append(raw.lower())
    q = (ctx.query or "").strip().lower()
    n = (ctx.name or "").strip().lower()
    for cache_key in keys:
        cached = get_cached("wikipedia", cache_key, 7 * 86400)
        if cached is None or is_disambiguation(cached) or is_generic_topic(cached, ctx.query or ""):
            continue
        cached_title = str(cached.get("title") or "").strip().lower()
        if n and q and n != q and cached_title == q:
            continue
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
        page = await http.get_json(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "prop": "extracts|description|pageimages|info",
                "exintro": 1,
                "explaintext": 1,
                "inprop": "url",
                "pithumbsize": 200,
                "titles": chosen_title,
                "format": "json",
                "redirects": 1,
            },
            headers=WIKI_HEADERS,
            retries=2,
            timeout=12.0,
        )
        pages = ((page or {}).get("query") or {}).get("pages") or {}
        rec = next(iter(pages.values()), None) if isinstance(pages, dict) else None
        if not rec or rec.get("missing") is not None:
            return SourceResult("wikipedia", False, error="no_match")
        extract = rec.get("extract")
        desc = rec.get("description")
        page_type = "disambiguation" if (isinstance(extract, str) and re.search(r"\bmay refer to\b", extract, re.I)) else "standard"
        thumb = rec.get("thumbnail") if isinstance(rec.get("thumbnail"), dict) else None
        summary = {
            "title": rec.get("title") or chosen_title,
            "extract": extract,
            "description": desc,
            "type": page_type,
            "thumbnail": {"source": thumb.get("source")} if thumb and thumb.get("source") else None,
            "content_urls": {
                "desktop": {"page": rec.get("fullurl") or rec.get("canonicalurl")},
            },
        }
        data = {"title": rec.get("title") or chosen_title, "summary": summary, "search": last_search}
        if (
            page_type != "disambiguation"
            and not is_disambiguation(data)
            and not is_generic_topic(data, ctx.query or "")
        ):
            for cache_key in keys or [chosen_title.lower()]:
                set_cached("wikipedia", cache_key, data)
        return SourceResult("wikipedia", True, data=data)
    except Exception as exc:
        return SourceResult("wikipedia", False, error=sanitize_error(exc))
