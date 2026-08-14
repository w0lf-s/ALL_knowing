from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from src.store import get_cached, load_news_day, save_news_day, set_cached

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
