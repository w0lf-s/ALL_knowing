from __future__ import annotations

import os
import re

from src.adapters import CompanyContext
from src.adapters.alpha_vantage import pick_av_symbol
from src.adapters.alpha_vantage import search_symbol as search_av_symbol
from src.adapters.finnhub import pick_best_symbol, search_symbol
from src.adapters.sec_edgar import load_ticker_map, resolve_cik
from src.adapters.wikipedia import fetch_wikipedia, is_disambiguation, is_generic_topic, search_titles
from src.adapters.yahoo import is_india_symbol, pick_yahoo_symbol, search_yahoo
from src.http import HttpClient
from src.rate_limit import RateLimits

_ORG_HINT = re.compile(
    r"\b(group|limited|ltd|inc|incorporated|corp|corporation|plc|llc|company|co|services|technologies|motors|steel|bank|industries|holdings|electronics|systems|labs|pvt|private)\b",
    re.I,
)
_LEGAL_TRIM = re.compile(
    r"\b(ltd|limited|inc|incorporated|corp|corporation|plc|llc|the|co)\b\.?",
    re.I,
)
_PAREN = re.compile(r"\s*\([^)]*\)\s*")


class AmbiguousCompanyError(Exception):
    def __init__(self, query: str, suggestions: list[str]):
        self.query = query
        self.suggestions = suggestions
        if suggestions:
            quoted = ",".join(f'"{s}"' for s in suggestions)
            msg = f"The name is too vague. Did you mean {quoted}"
        else:
            msg = "The name is too vague. Try a full company name or stock ticker."
        super().__init__(msg)

_SEARCH_ALIASES: dict[str, list[str]] = {
    "google": ["Alphabet", "GOOGL"],
    "youtube": ["Alphabet", "GOOGL"],
    "instagram": ["Meta", "META"],
    "facebook": ["Meta", "META"],
    "whatsapp": ["Meta", "META"],
    "amazon": ["Amazon.com", "AMZN"],
    "aws": ["Amazon.com", "AMZN"],
    "apple": ["Apple Inc", "AAPL"],
    "microsoft": ["Microsoft", "MSFT"],
    "meta": ["Meta Platforms", "META"],
    "tesla": ["Tesla", "TSLA"],
    "linkedin": ["Microsoft", "MSFT"],
    "infosys": ["INFY.NS", "Infosys"],
    "tcs": ["TCS.NS", "Tata Consultancy Services"],
    "reliance": ["RELIANCE.NS", "Reliance Industries"],
    "hdfc": ["HDFCBANK.NS", "HDFC Bank"],
    "wipro": ["WIPRO.NS", "Wipro"],
    "nvdia": ["Nvidia", "NVDA"],
    "nvidia": ["Nvidia", "NVDA"],
    "boat": ["Imagine Marketing", "boAt"],
    "imagine marketing": ["Imagine Marketing", "boAt"],
}

_TICKER_RE = re.compile(r"^[A-Z]{1,5}(\.(NS|BO|NSE|BSE|US))?$")


def _plausible_ticker(ticker: str | None, name: str | None = None) -> bool:
    if not ticker:
        return False
    base = ticker.upper().split(".", 1)[0]
    if is_india_symbol(ticker) and 1 <= len(base) <= 12:
        return True
    if not re.match(r"^[A-Z0-9.]{1,5}$", base):
        return False
    if name:
        compact = re.sub(r"[^A-Z]", "", str(name).upper())
        if base == compact and len(base) > 5:
            return False
    return True


def _ticker_score(ticker: str, name: str | None, query: str) -> int:
    q = query.strip().lower()
    score = 10
    if not _plausible_ticker(ticker, name):
        return -50
    if name and q in str(name).lower():
        score += 40
    base = ticker.upper().split(".", 1)[0]
    if base == query.strip().upper() and _plausible_ticker(ticker):
        score += 50
    if is_india_symbol(ticker):
        score += 20
    if ticker.upper().endswith((".US",)):
        score += 15
    if "." not in ticker and 1 <= len(ticker) <= 5:
        score += 12
    return score


def _suggest_key(name: str) -> str:
    s = _PAREN.sub(" ", name)
    s = _LEGAL_TRIM.sub("", s)
    return " ".join(s.lower().split())


def _pick_suggestions(query: str, names: list[str], limit: int = 3) -> list[str]:
    q = query.strip().lower()
    picked: list[str] = []
    seen: set[str] = set()
    ranked: list[tuple[int, str]] = []
    for raw in names:
        text = " ".join(str(raw).split()).strip()
        if not text or text.lower() == q:
            continue
        key = _suggest_key(text)
        if not key or key == q or key in seen:
            continue
        score = 20
        if _ORG_HINT.search(text):
            score += 40
        if q and q in text.lower():
            score += 15
        ranked.append((score, text))
        seen.add(key)
    ranked.sort(key=lambda x: (-x[0], len(x[1])))
    for score, text in ranked:
        if score < 20:
            continue
        picked.append(text)
        if len(picked) >= limit:
            break
    return picked


def _alias_name(query: str) -> str | None:
    for alt in _SEARCH_ALIASES.get(query.lower().strip(), []):
        if _TICKER_RE.match(alt.upper()) and "." not in alt and len(alt) <= 5:
            continue
        if alt.lower() == query.lower().strip():
            continue
        return alt
    return None


def _name_matches_term(name: str | None, term: str) -> bool:
    if not name or not term:
        return False
    nl = str(name).lower()
    tl = term.lower().strip()
    if tl in nl:
        return True
    words = [w for w in re.split(r"\W+", tl) if len(w) > 3]
    return bool(words) and all(w in nl for w in words)


async def _lookup_ticker(
    http: HttpClient,
    limits: RateLimits,
    query: str,
) -> tuple[str | None, str | None, list[str]]:
    q = query.strip()
    aliases = _SEARCH_ALIASES.get(query.lower().strip(), [])
    terms: list[str] = []
    for alt in aliases:
        if alt.lower() == query.lower().strip():
            continue
        if alt not in terms:
            terms.append(alt)
    if not terms:
        terms.append(query)
    found: list[tuple[int, str, str | None]] = []
    names: list[str] = []
    for term in terms:
        if _TICKER_RE.match(term.upper()) and "." in term:
            found.append((90, term.upper(), query))
        fh = await search_symbol(http, limits, term)
        if fh.ok and isinstance(fh.data, dict):
            search = fh.data.get("search") or {}
            for item in search.get("result") or []:
                desc = item.get("description")
                if desc:
                    names.append(str(desc).strip())
            if search.get("result"):
                ticker, name = pick_best_symbol(search, term)
                if ticker and (not aliases or _name_matches_term(name, term) or any(_name_matches_term(name, a) for a in aliases)):
                    found.append((_ticker_score(ticker, name, query), ticker, name or query))
        yh = await search_yahoo(http, term)
        if yh.ok and isinstance(yh.data, dict):
            quotes = yh.data.get("search") or []
            if isinstance(quotes, list) and quotes:
                for item in quotes:
                    typ = str(item.get("quoteType") or "").upper()
                    if typ and typ not in {"EQUITY", "ETF", ""}:
                        continue
                    nm = item.get("longname") or item.get("shortname") or item.get("name")
                    if nm:
                        names.append(str(nm).strip())
                ticker, name, _exch = pick_yahoo_symbol(quotes, term)
                if ticker and (not aliases or _name_matches_term(name, term) or any(_name_matches_term(name, a) for a in aliases)):
                    found.append((_ticker_score(ticker, name, query) + 8, ticker, name or query))
        av = await search_av_symbol(http, term)
        if av.ok and isinstance(av.data, dict):
            matches = av.data.get("search") or []
            if isinstance(matches, list) and matches:
                ticker, name = pick_av_symbol(matches, term)
                if ticker and (not aliases or _name_matches_term(name, term) or any(_name_matches_term(name, a) for a in aliases)):
                    found.append((_ticker_score(ticker, name, query), ticker, name or query))
                    if name:
                        names.append(str(name).strip())
        if found:
            found.sort(key=lambda x: x[0], reverse=True)
            best = found[0]
            if best[0] > 0 and _plausible_ticker(best[1], best[2]):
                return best[1], best[2], names
    return None, (_alias_name(query) or query), names


async def resolve_identity(http: HttpClient, limits: RateLimits, query: str) -> CompanyContext:
    ctx = CompanyContext(query=query)
    ticker, name, candidate_names = await _lookup_ticker(http, limits, query)
    ctx.ticker = ticker if _plausible_ticker(ticker, name) else None
    ctx.name = name or _alias_name(query) or query

    wiki = await fetch_wikipedia(http, CompanyContext(query=query, name=ctx.name))
    q_key = query.lower().strip()
    wiki_titles = search_titles(wiki.data) if wiki.ok and isinstance(wiki.data, dict) else []
    suggestions = _pick_suggestions(query, wiki_titles + candidate_names)
    wiki_vague = bool(wiki.ok and isinstance(wiki.data, dict) and is_disambiguation(wiki.data))
    wiki_generic = bool(wiki.ok and isinstance(wiki.data, dict) and is_generic_topic(wiki.data, query))
    if wiki_vague and q_key not in _SEARCH_ALIASES and len(suggestions) >= 2:
        raise AmbiguousCompanyError(query, suggestions)
    if wiki.ok and isinstance(wiki.data, dict) and not wiki_vague and not wiki_generic:
        ctx.wiki_title = wiki.data.get("title")
        wiki_name = wiki.data.get("title") or (wiki.data.get("summary") or {}).get("title")
        if wiki_name and (not ctx.ticker or not _plausible_ticker(ctx.ticker, wiki_name)):
            t2, n2, _extra = await _lookup_ticker(http, limits, wiki_name)
            if _plausible_ticker(t2, n2):
                ctx.ticker = t2
                if n2:
                    ctx.name = n2
        elif wiki_name and wiki_name.strip().lower() != q_key:
            ctx.name = wiki_name

    user_agent = os.getenv("SEC_USER_AGENT", "").strip() or "company_search contact@example.com"
    if ctx.ticker and not is_india_symbol(ctx.ticker):
        try:
            sec_ticker = ctx.ticker.split(".", 1)[0] if "." in ctx.ticker else ctx.ticker
            ticker_map = await load_ticker_map(http, limits, user_agent)
            cik, title, _ = resolve_cik(ticker_map, sec_ticker)
            ctx.cik = cik
            if title:
                ctx.name = title
        except Exception:
            pass

    return ctx
