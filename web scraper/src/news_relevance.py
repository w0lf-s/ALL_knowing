from __future__ import annotations

import json
import os
import re
from typing import Any

from openai import OpenAI


def _client() -> OpenAI | None:
    key = os.getenv("GROQ_API_KEY", "").strip()
    if not key:
        return None
    return OpenAI(api_key=key, base_url="https://api.groq.com/openai/v1")


def _normalize_name(name: str) -> str:
    n = name.lower().strip()
    for suffix in (
        " incorporated",
        " corporation",
        " company",
        " limited",
        " ltd",
        " llc",
        " inc",
        " corp",
        " co",
        " plc",
        " nv",
        " sa",
    ):
        if n.endswith(suffix):
            n = n[: -len(suffix)].strip()
        if n.endswith("."):
            n = n[:-1].strip()
    return n


def local_relevant(
    article: dict[str, Any],
    *,
    company_name: str,
    ticker: str | None,
    query: str,
) -> bool:
    text = f"{article.get('title') or ''} {article.get('summary') or ''}".lower()
    if not text.strip():
        return False
    if ticker:
        tk = ticker.lower().strip()
        if re.search(rf"(?<![a-z0-9]){re.escape(tk)}(?![a-z0-9])", text):
            return True
    names = {_normalize_name(company_name), _normalize_name(query), company_name.lower(), query.lower()}
    names = {n for n in names if n and len(n) >= 3}
    for n in names:
        if n in text:
            return True
    return False


def filter_relevant_articles(
    articles: list[dict[str, Any]],
    *,
    company_name: str,
    ticker: str | None,
    query: str,
    limit: int = 8,
    use_groq: bool = True,
) -> list[dict[str, Any]]:
    if not articles:
        return []

    indexed = [{"id": i, "title": a.get("title"), "summary": (a.get("summary") or "")[:240]} for i, a in enumerate(articles)]

    if use_groq:
        client = _client()
        model = os.getenv("NEWS_GROQ_MODEL") or os.getenv("GROQ_MODEL") or "llama-3.1-8b-instant"
        if client is not None:
            payload = {
                "company_name": company_name or query,
                "ticker": ticker,
                "query": query,
                "articles": indexed,
            }
            system = (
                "You filter news relevance for a company. "
                "Return ONLY valid JSON: {\"relevant_ids\": [int, ...]}. "
                "Mark an article relevant ONLY if its title/summary is primarily about that company "
                "(products, earnings, lawsuits, leadership, stock as main subject). "
                "Reject articles that only mention the ticker in passing, generic market pieces, "
                "unrelated tech tutorials, or other companies. "
                "Prefer precision over recall."
            )
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                    temperature=0.1,
                    response_format={"type": "json_object"},
                )
                data = json.loads(resp.choices[0].message.content or "{}")
                ids = data.get("relevant_ids") or []
                chosen: list[dict[str, Any]] = []
                seen: set[int] = set()
                for raw_id in ids:
                    try:
                        i = int(raw_id)
                    except Exception:
                        continue
                    if i in seen or i < 0 or i >= len(articles):
                        continue
                    seen.add(i)
                    chosen.append(articles[i])
                    if len(chosen) >= limit:
                        break
                if chosen:
                    return chosen
            except Exception:
                pass

    fallback = [
        a
        for a in articles
        if local_relevant(a, company_name=company_name or query, ticker=ticker, query=query)
    ]
    return fallback[:limit]
