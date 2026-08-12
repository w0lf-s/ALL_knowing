from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_EMAIL_COOKIE_NAMES = ("user_email", "session_user", "logged_in_email")


def extract_emails_from_text(text: str) -> list[str]:
    if not text:
        return []
    return sorted({m.group(0).lower() for m in _EMAIL_RE.finditer(str(text))})


def emails_from_cookie_snapshot(snapshot: dict[str, Any]) -> list[str]:
    cookies = snapshot.get("cookies") or []
    found: set[str] = set()
    by_name: dict[str, str] = {}
    for cookie in cookies:
        if not isinstance(cookie, dict):
            continue
        name = str(cookie.get("name") or "")
        value = str(cookie.get("value") or "")
        if name:
            by_name[name] = value
        found.update(extract_emails_from_text(value))
    for key in _EMAIL_COOKIE_NAMES:
        found.update(extract_emails_from_text(by_name.get(key, "")))
    pre = ((snapshot.get("parsed") or {}).get("email") or "").strip().lower()
    if pre:
        found.add(pre)
    return sorted(found)


def load_cookie_snapshot(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("cookie snapshot must be a JSON object")
    return data


def primary_email_from_cookie_file(path: Path) -> str:
    snapshot = load_cookie_snapshot(path)
    emails = emails_from_cookie_snapshot(snapshot)
    if not emails:
        raise ValueError(f"No email found in cookie snapshot: {path}")
    return emails[0]
