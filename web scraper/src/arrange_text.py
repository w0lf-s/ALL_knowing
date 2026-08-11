from __future__ import annotations

import json
import os

from openai import OpenAI

from src.schema import CompanyDossier


def _client() -> OpenAI | None:
    key = os.getenv("GROQ_API_KEY", "").strip()
    if not key:
        return None
    return OpenAI(api_key=key, base_url="https://api.groq.com/openai/v1")


def _trim(text: str | None, n: int) -> str | None:
    if not text:
        return None
    t = text.strip()
    return t if len(t) <= n else t[: n - 1] + "…"


def arrange_text(dossier: CompanyDossier) -> CompanyDossier:
    client = _client()
    if client is None:
        return dossier

    model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    max_chars = int(os.getenv("GROQ_ARRANGE_MAX_CHARS", "60000"))

    desc_candidates = []
    if dossier.overview.description:
        desc_candidates.append({"via": "current", "text": _trim(dossier.overview.description, 2500)})

    fin_snapshot = {
        k: getattr(dossier.financials, k)
        for k in (
            "market_cap",
            "revenue",
            "revenue_ttm",
            "eps",
            "pe_ratio",
            "profit_margin",
            "dividend_yield",
            "beta",
            "week_52_high",
            "week_52_low",
        )
        if getattr(dossier.financials, k) is not None
    }

    payload = {
        "name": dossier.resolved.name or dossier.query,
        "ticker": dossier.resolved.ticker,
        "description_candidates": desc_candidates,
        "short_description": dossier.overview.short_description,
        "financials": fin_snapshot,
    }
    raw = json.dumps(payload, ensure_ascii=False)
    if len(raw) > max_chars:
        raw = raw[:max_chars]

    system = (
        "You arrange company intelligence text. Return ONLY valid JSON with keys: "
        "description (string|null), short_description (string|null), "
        "highlights (string array). "
        "Do not invent facts. Prefer source text. highlights: 3-8 bullets from provided financials numbers only. "
        "Do not mention or summarize news."
    )
    user = f"Arrange text for this company payload:\n{raw}"

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content or "{}"
        data = json.loads(content)
    except Exception:
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system + " Fix to valid JSON only."},
                    {"role": "user", "content": user},
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            data = json.loads(resp.choices[0].message.content or "{}")
        except Exception:
            return dossier

    if isinstance(data.get("description"), str) and data["description"].strip():
        dossier.overview.description = data["description"].strip()
    if isinstance(data.get("short_description"), str) and data["short_description"].strip():
        dossier.overview.short_description = data["short_description"].strip()
    highlights = data.get("highlights")
    if isinstance(highlights, list):
        dossier.financials.highlights = [str(h).strip() for h in highlights if str(h).strip()][:8]

    return dossier
