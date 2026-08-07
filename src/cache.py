from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from src.paths import CACHE, NEWS_DIR, ensure_dirs


def _safe_key(key: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", key)[:180]


def cache_path(source: str, key: str) -> Path:
    ensure_dirs()
    d = CACHE / source
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{_safe_key(key)}.json"


def get_cached(source: str, key: str, ttl_seconds: int) -> Any | None:
    path = cache_path(source, key)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        fetched_at = payload.get("fetched_at")
        if not fetched_at:
            return None
        ts = datetime.fromisoformat(fetched_at)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - ts).total_seconds()
        if age > ttl_seconds:
            return None
        return payload.get("data")
    except Exception:
        return None


def set_cached(source: str, key: str, data: Any) -> None:
    path = cache_path(source, key)
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def news_day_path(company_key: str, day: str | None = None) -> Path:
    ensure_dirs()
    d = day or datetime.now(timezone.utc).date().isoformat()
    folder = NEWS_DIR / company_key
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{d}.json"


def load_news_day(company_key: str) -> dict[str, Any] | None:
    path = news_day_path(company_key)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_news_day(company_key: str, data: dict[str, Any]) -> Path:
    path = news_day_path(company_key)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
}


def normalize_url(url: str | None) -> str | None:
    if not url:
        return None
    try:
        parsed = urlparse(url.strip())
        q = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k.lower() not in TRACKING_PARAMS]
        cleaned = parsed._replace(query=urlencode(q), fragment="")
        return urlunparse(cleaned)
    except Exception:
        return url
