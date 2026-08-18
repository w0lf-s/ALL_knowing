from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from src.paths import BOOKMARKS_PATH, CACHE, COMPANY_DIR, NEWS_DIR, PEOPLE_DIR, WORKSPACE_PATH, company_key, ensure_dirs

_client = None
_client_checked = False
NEWS_TTL_S = 24 * 3600


def news_is_fresh(fetched_at: Any) -> bool:
    ts = _parse_ts(fetched_at)
    if ts <= 0:
        return False
    return (datetime.now(timezone.utc).timestamp() - ts) <= NEWS_TTL_S


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(val: Any) -> float:
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    text = str(val).strip().replace("Z", "+00:00")
    try:
        ts = datetime.fromisoformat(text)
    except Exception:
        return 0.0
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.timestamp()


def _jsonable(data: Any) -> Any:
    return json.loads(json.dumps(data, default=str))


def _safe_key(key: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", key)[:180]


def _sb():
    global _client, _client_checked
    if _client_checked:
        return _client
    _client_checked = True
    url = (os.getenv("SUPABASE_URL") or "").strip()
    key = (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not url or not key:
        _client = None
        return None
    try:
        from supabase import create_client

        _client = create_client(url, key)
    except Exception:
        _client = None
    return _client


def using_db() -> bool:
    return _sb() is not None


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _read_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _query_matches_dossier(data: dict, query: str) -> bool:
    q = query.lower().strip()
    if not q or not isinstance(data, dict):
        return False
    want = company_key(query)
    resolved = data.get("resolved") or {}
    fields = [data.get("query"), resolved.get("ticker"), resolved.get("name")]
    for raw in fields:
        text = str(raw or "").strip()
        if not text:
            continue
        if text.lower() == q or company_key(text) == want:
            return True
    return False


def cache_path(source: str, key: str) -> Path:
    ensure_dirs()
    d = CACHE / source
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{_safe_key(key)}.json"


def news_day_path(ckey: str, day: str | None = None) -> Path:
    ensure_dirs()
    d = day or datetime.now(timezone.utc).date().isoformat()
    folder = NEWS_DIR / ckey
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{d}.json"


def get_cached(source: str, key: str, ttl_seconds: int) -> Any | None:
    safe = _safe_key(key)
    client = _sb()
    if client is not None:
        try:
            res = (
                client.table("source_cache")
                .select("data, fetched_at")
                .eq("source", source)
                .eq("cache_key", safe)
                .limit(1)
                .execute()
            )
            rows = res.data or []
            if rows:
                fetched_at = rows[0].get("fetched_at")
                age = datetime.now(timezone.utc).timestamp() - _parse_ts(fetched_at)
                if age <= ttl_seconds:
                    return rows[0].get("data")
        except Exception:
            pass
    path = CACHE / source / f"{_safe_key(key)}.json"
    payload = _read_json(path)
    if not isinstance(payload, dict):
        return None
    fetched_at = payload.get("fetched_at")
    if not fetched_at:
        return None
    try:
        ts = datetime.fromisoformat(str(fetched_at))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - ts).total_seconds()
        if age > ttl_seconds:
            return None
        return payload.get("data")
    except Exception:
        return None


def set_cached(source: str, key: str, data: Any) -> None:
    fetched_at = _now_iso()
    payload = {"fetched_at": fetched_at, "data": data}
    client = _sb()
    if client is None:
        path = cache_path(source, key)
        path.write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")
        return
    try:
        client.table("source_cache").upsert(
            {
                "source": source,
                "cache_key": _safe_key(key),
                "data": _jsonable(data),
                "fetched_at": fetched_at,
            }
        ).execute()
    except Exception:
        pass


def load_news_day(ckey: str, day: str | None = None) -> dict[str, Any] | None:
    d = day or datetime.now(timezone.utc).date().isoformat()
    purge_stale_news()
    client = _sb()
    if client is not None:
        try:
            res = (
                client.table("news_days")
                .select("data")
                .eq("company_key", ckey)
                .eq("day", d)
                .limit(1)
                .execute()
            )
            rows = res.data or []
            if rows and isinstance(rows[0].get("data"), dict):
                data = rows[0]["data"]
                if news_is_fresh(data.get("fetched_at") or d):
                    return data
                client.table("news_days").delete().eq("company_key", ckey).eq("day", d).execute()
        except Exception:
            pass
    path = NEWS_DIR / ckey / f"{d}.json"
    data = _read_json(path)
    if isinstance(data, dict) and news_is_fresh(data.get("fetched_at") or d):
        return data
    if path.exists():
        path.unlink()
    return None


def save_news_day(ckey: str, data: dict[str, Any], day: str | None = None) -> Path:
    d = day or datetime.now(timezone.utc).date().isoformat()
    path = NEWS_DIR / ckey / f"{d}.json"
    client = _sb()
    if client is not None:
        try:
            client.table("news_days").upsert(
                {
                    "company_key": ckey,
                    "day": d,
                    "data": _jsonable(data),
                }
            ).execute()
        except Exception:
            pass
        return path
    news_day_path(ckey, d).write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


def _empty_news(news: dict | None) -> dict[str, Any]:
    lookback = 3
    if isinstance(news, dict) and news.get("lookback_days") not in (None, ""):
        lookback = news.get("lookback_days")
    return {"digest_summary": None, "lookback_days": lookback, "articles": [], "fetched_at": None}


def expire_dossier_news(dossier: dict) -> tuple[dict, bool]:
    if not isinstance(dossier, dict):
        return dossier, False
    news = dossier.get("news")
    articles = news.get("articles") if isinstance(news, dict) else None
    if not articles:
        return dossier, False
    ts = None
    if isinstance(news, dict):
        ts = news.get("fetched_at")
    if not ts:
        ts = (dossier.get("meta") or {}).get("generated_at")
    if news_is_fresh(ts):
        return dossier, False
    out = dict(dossier)
    out["news"] = _empty_news(news if isinstance(news, dict) else None)
    return out, True


_last_news_purge = 0.0


def purge_stale_news() -> None:
    global _last_news_purge
    now = datetime.now(timezone.utc).timestamp()
    if now - _last_news_purge < 60:
        return
    _last_news_purge = now
    client = _sb()
    if client is not None:
        try:
            res = client.table("news_days").select("company_key, day, data").execute()
            for row in res.data or []:
                data = row.get("data") if isinstance(row.get("data"), dict) else {}
                ts = data.get("fetched_at") or row.get("day")
                if news_is_fresh(ts):
                    continue
                client.table("news_days").delete().eq("company_key", row.get("company_key")).eq("day", row.get("day")).execute()
        except Exception:
            pass
    if NEWS_DIR.exists():
        for path in NEWS_DIR.rglob("*.json"):
            if not path.is_file():
                continue
            data = _read_json(path)
            ts = data.get("fetched_at") if isinstance(data, dict) else None
            try:
                mtime = path.stat().st_mtime
            except Exception:
                mtime = 0.0
            if news_is_fresh(ts or mtime):
                continue
            path.unlink()


def _ensure_dossier_summary(dossier: dict[str, Any]) -> tuple[dict, bool]:
    if not isinstance(dossier, dict):
        return dossier, False
    overview = dict(dossier.get("overview") or {})
    resolved = dossier.get("resolved") or {}
    short = str(overview.get("short_description") or "").strip()
    desc = str(overview.get("description") or "").strip()
    if short and desc:
        return dossier, False
    name = overview.get("legal_name") or resolved.get("name") or dossier.get("query") or "This company"
    ticker = resolved.get("ticker")
    kind = overview.get("industry") or overview.get("sector")
    country = overview.get("country")
    label = str(name)
    if ticker:
        label = f"{label} ({ticker})"
    if kind:
        summary = f"{label} is a {kind} company"
    else:
        summary = f"{label} is a publicly listed company"
    if country:
        summary += f" based in {country}"
    summary += "."
    changed = False
    if not short:
        overview["short_description"] = summary
        changed = True
    if not desc:
        overview["description"] = overview.get("short_description") or summary
        changed = True
    if not changed:
        return dossier, False
    out = dict(dossier)
    out["overview"] = overview
    return out, True


def _persist_company(key: str, dossier: dict[str, Any], updated_at: float | None = None, disk: bool = False) -> None:
    dossier, _ = _ensure_dossier_summary(dossier)
    client = _sb()
    if client is None or disk:
        ensure_dirs()
        path = COMPANY_DIR / f"{key}.json"
        _write_json(path, dossier)
    if client is None:
        return
    resolved = dossier.get("resolved") or {}
    stamp = _now_iso()
    if updated_at:
        stamp = datetime.fromtimestamp(updated_at, tz=timezone.utc).isoformat()
    try:
        client.table("companies").upsert(
            {
                "key": key,
                "query": dossier.get("query") or key,
                "ticker": resolved.get("ticker"),
                "name": resolved.get("name") or (dossier.get("overview") or {}).get("legal_name"),
                "dossier": _jsonable(dossier),
                "updated_at": stamp,
            }
        ).execute()
    except Exception:
        pass


def put_company(key: str, dossier: dict[str, Any], *, disk: bool = False) -> None:
    _persist_company(key, dossier, disk=disk)


def get_company(key: str) -> dict[str, Any] | None:
    rec = get_company_record(key)
    return rec["dossier"] if rec else None


def get_company_record(key: str) -> dict[str, Any] | None:
    client = _sb()
    if client is not None:
        try:
            res = (
                client.table("companies")
                .select("key, dossier, updated_at")
                .eq("key", key)
                .limit(1)
                .execute()
            )
            rows = res.data or []
            if rows and isinstance(rows[0].get("dossier"), dict):
                dossier, changed = expire_dossier_news(rows[0]["dossier"])
                dossier, filled = _ensure_dossier_summary(dossier)
                rec = {
                    "key": rows[0].get("key") or key,
                    "dossier": dossier,
                    "updated_at": _parse_ts(rows[0].get("updated_at")),
                }
                if changed or filled:
                    _persist_company(rec["key"], dossier, rec["updated_at"], disk=False)
                    if changed:
                        purge_stale_news()
                return rec
        except Exception:
            pass
    path = COMPANY_DIR / f"{key}.json"
    data = _read_json(path)
    if not isinstance(data, dict):
        return None
    try:
        mtime = path.stat().st_mtime
    except Exception:
        mtime = 0.0
    dossier, changed = expire_dossier_news(data)
    dossier, filled = _ensure_dossier_summary(dossier)
    rec = {"key": key, "dossier": dossier, "updated_at": mtime}
    if changed or filled:
        _persist_company(key, dossier, mtime, disk=False)
        if changed:
            purge_stale_news()
    return rec


def find_company_record(query: str) -> dict[str, Any] | None:
    q = str(query or "").strip()
    if not q:
        return None
    direct = get_company_record(company_key(q))
    if direct:
        return direct
    for rec in list_company_records():
        if _query_matches_dossier(rec["dossier"], q):
            return rec
    return None


def list_company_records() -> list[dict[str, Any]]:
    client = _sb()
    if client is not None:
        try:
            res = (
                client.table("companies")
                .select("key, dossier, updated_at")
                .order("updated_at", desc=True)
                .limit(5000)
                .execute()
            )
            out = []
            for row in res.data or []:
                if not isinstance(row.get("dossier"), dict):
                    continue
                dossier, _changed = expire_dossier_news(row["dossier"])
                dossier, _filled = _ensure_dossier_summary(dossier)
                out.append({
                    "key": row.get("key") or "",
                    "dossier": dossier,
                    "updated_at": _parse_ts(row.get("updated_at")),
                })
            return out
        except Exception:
            return []
    ensure_dirs()
    items = []
    for path in COMPANY_DIR.glob("*.json"):
        data = _read_json(path)
        if not isinstance(data, dict):
            continue
        try:
            mtime = path.stat().st_mtime
        except Exception:
            mtime = 0.0
        items.append({"key": path.stem, "dossier": data, "updated_at": mtime})
    items.sort(key=lambda r: r["updated_at"], reverse=True)
    cleaned = []
    for rec in items:
        dossier, changed = expire_dossier_news(rec["dossier"])
        dossier, filled = _ensure_dossier_summary(dossier)
        rec = {"key": rec["key"], "dossier": dossier, "updated_at": rec["updated_at"]}
        if changed or filled:
            _persist_company(rec["key"], dossier, rec["updated_at"], disk=False)
        cleaned.append(rec)
    return cleaned


def list_companies() -> list[dict[str, Any]]:
    return [r["dossier"] for r in list_company_records()]


def _expire_workspace_leads(leads: list) -> tuple[list, bool]:
    changed = False
    out = []
    for lead in leads:
        if not isinstance(lead, dict):
            out.append(lead)
            continue
        result = lead.get("result") if isinstance(lead.get("result"), dict) else None
        company = result.get("company") if result and isinstance(result.get("company"), dict) else None
        news = company.get("news") if company and isinstance(company.get("news"), dict) else None
        articles = news.get("articles") if news else None
        ts = None
        if news:
            ts = news.get("fetched_at")
        if not ts and company:
            ts = (company.get("meta") or {}).get("generated_at")
        if articles and not news_is_fresh(ts):
            lead = dict(lead)
            result = dict(result or {})
            company = dict(company or {})
            company["news"] = _empty_news(news)
            result["company"] = company
            lead["result"] = result
            lead["newsLookedUp"] = False
            changed = True
        out.append(lead)
    return out, changed


def _local_bookmark_keys() -> list[str]:
    data = _read_json(BOOKMARKS_PATH)
    if isinstance(data, list):
        return [str(x).strip() for x in data if str(x).strip()]
    return []


def _write_local_bookmarks(keys: list[str]) -> None:
    BOOKMARKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _write_json(BOOKMARKS_PATH, keys)


def add_bookmark(key: str) -> None:
    k = str(key or "").strip()
    if not k:
        return
    client = _sb()
    if client is None:
        local = _local_bookmark_keys()
        if k not in local:
            local.append(k)
            _write_local_bookmarks(local)
        return
    try:
        client.table("bookmarks").upsert({"company_key": k, "created_at": _now_iso()}).execute()
        return
    except Exception:
        local = _local_bookmark_keys()
        if k not in local:
            local.append(k)
            _write_local_bookmarks(local)


def remove_bookmark(key: str) -> None:
    k = str(key or "").strip()
    if not k:
        return
    client = _sb()
    if client is None:
        _write_local_bookmarks([x for x in _local_bookmark_keys() if x != k])
        return
    try:
        client.table("bookmarks").delete().eq("company_key", k).execute()
    except Exception:
        pass


def _migrate_workspace_bookmarks() -> None:
    keys: list[str] = []
    client = _sb()
    if client is not None:
        try:
            res = client.table("workspace").select("bookmarks").eq("id", 1).limit(1).execute()
            rows = res.data or []
            if rows and isinstance(rows[0].get("bookmarks"), list):
                keys = [str(x).strip() for x in rows[0]["bookmarks"] if str(x).strip()]
        except Exception:
            pass
    if not keys:
        data = _read_json(WORKSPACE_PATH)
        if isinstance(data, dict) and isinstance(data.get("bookmarks"), list):
            keys = [str(x).strip() for x in data["bookmarks"] if str(x).strip()]
    for item in keys:
        add_bookmark(item)


def list_bookmarks() -> list[str]:
    local = _local_bookmark_keys()
    client = _sb()
    if client is not None:
        try:
            res = client.table("bookmarks").select("company_key").execute()
            keys = [str(r.get("company_key") or "").strip() for r in (res.data or []) if str(r.get("company_key") or "").strip()]
            if keys:
                return list(dict.fromkeys(keys))
        except Exception:
            pass
        _migrate_workspace_bookmarks()
        try:
            res = client.table("bookmarks").select("company_key").execute()
            keys = [str(r.get("company_key") or "").strip() for r in (res.data or []) if str(r.get("company_key") or "").strip()]
            if keys:
                return list(dict.fromkeys(keys))
        except Exception:
            pass
        if local:
            for item in local:
                add_bookmark(item)
            return list(dict.fromkeys(local))
    if local:
        return local
    data = _read_json(WORKSPACE_PATH)
    if isinstance(data, dict) and isinstance(data.get("bookmarks"), list):
        keys = [str(x).strip() for x in data["bookmarks"] if str(x).strip()]
        if keys:
            _write_local_bookmarks(keys)
            return keys
    return []


def get_workspace() -> dict[str, Any]:
    purge_stale_news()
    client = _sb()
    if client is not None:
        try:
            res = client.table("workspace").select("bookmarks, leads, linkedin").eq("id", 1).limit(1).execute()
            rows = res.data or []
            if rows:
                row = rows[0]
                leads = row.get("leads") if isinstance(row.get("leads"), list) else []
                leads, changed = _expire_workspace_leads(leads)
                payload = {
                    "exists": True,
                    "bookmarks": list_bookmarks(),
                    "leads": leads,
                    "linkedin": row.get("linkedin") if isinstance(row.get("linkedin"), dict) else {},
                }
                if changed:
                    put_workspace(payload["bookmarks"], payload["leads"], payload["linkedin"])
                return payload
        except Exception:
            pass
    data = _read_json(WORKSPACE_PATH)
    if isinstance(data, dict):
        leads = data.get("leads") if isinstance(data.get("leads"), list) else []
        leads, changed = _expire_workspace_leads(leads)
        payload = {
            "exists": True,
            "bookmarks": list_bookmarks(),
            "leads": leads,
            "linkedin": data.get("linkedin") if isinstance(data.get("linkedin"), dict) else {},
        }
        if changed:
            put_workspace(payload["bookmarks"], payload["leads"], payload["linkedin"])
        return payload
    return {"exists": False, "bookmarks": list_bookmarks(), "leads": [], "linkedin": {}}


def _workspace_linkedin(linkedin: Any) -> dict[str, Any]:
    if not isinstance(linkedin, dict):
        return {}
    return {
        "url": linkedin.get("url") or "",
        "name": linkedin.get("name") or "",
        "company": linkedin.get("company") or "",
        "role": linkedin.get("role") or "",
        "location": linkedin.get("location") or "",
        "email": linkedin.get("email") or "",
        "phone": linkedin.get("phone") or "",
        "profiles": linkedin.get("profiles") if isinstance(linkedin.get("profiles"), list) else [],
        "candidateUrls": linkedin.get("candidateUrls") if isinstance(linkedin.get("candidateUrls"), list) else [],
        "candidates": linkedin.get("candidates") if isinstance(linkedin.get("candidates"), list) else [],
        "searched": bool(linkedin.get("searched")),
    }


def _workspace_leads(leads: Any) -> list:
    out = []
    if not isinstance(leads, list):
        return out
    for lead in leads:
        if not isinstance(lead, dict):
            continue
        out.append({
            "id": lead.get("id"),
            "email": lead.get("email"),
            "parsed": lead.get("parsed"),
            "from_sample_cookie": lead.get("from_sample_cookie"),
            "result": lead.get("result"),
            "error": lead.get("error"),
            "viewOpen": bool(lead.get("viewOpen")),
            "newsLookedUp": bool(lead.get("newsLookedUp")),
        })
    return out


def put_workspace(bookmarks: list, leads: list, linkedin: dict) -> None:
    payload = {
        "leads": _workspace_leads(leads),
        "linkedin": _workspace_linkedin(linkedin),
    }
    incoming = [str(x).strip() for x in (bookmarks or []) if str(x).strip()]
    for k in incoming:
        add_bookmark(k)
    client = _sb()
    if client is None:
        WORKSPACE_PATH.parent.mkdir(parents=True, exist_ok=True)
        existing = _read_json(WORKSPACE_PATH)
        disk = existing if isinstance(existing, dict) else {}
        disk["leads"] = payload["leads"]
        disk["linkedin"] = payload["linkedin"]
        disk["bookmarks"] = list(dict.fromkeys((disk.get("bookmarks") if isinstance(disk.get("bookmarks"), list) else []) + incoming))
        _write_json(WORKSPACE_PATH, disk)
        return
    try:
        client.table("workspace").upsert(
            {
                "id": 1,
                "leads": _jsonable(payload["leads"]),
                "linkedin": _jsonable(payload["linkedin"]),
                "updated_at": _now_iso(),
            }
        ).execute()
    except Exception:
        pass


def person_key(linkedin_url: str = "", name: str = "", company: str = "") -> str:
    url = str(linkedin_url or "").split("?")[0].rstrip("/").lower()
    if "/in/" in url:
        return _safe_key(url)
    blob = f"{(name or '').strip()} {(company or '').strip()}".strip()
    return company_key(blob) if blob else "unknown"


def _person_path(key: str) -> Path:
    PEOPLE_DIR.mkdir(parents=True, exist_ok=True)
    return PEOPLE_DIR / f"{_safe_key(key)}.json"


def get_person(key: str) -> dict[str, Any] | None:
    k = str(key or "").strip()
    if not k:
        return None
    client = _sb()
    if client is not None:
        try:
            res = client.table("people").select("*").eq("key", k).limit(1).execute()
            rows = res.data or []
            if rows and isinstance(rows[0], dict):
                return rows[0]
        except Exception:
            pass
    data = _read_json(_person_path(k))
    return data if isinstance(data, dict) else None


_NAME_STOP = {"the", "and", "for", "with", "from", "3rd", "2nd", "1st"}


def _li_slug(url: str) -> str:
    match = re.search(r"linkedin\.com/in/([^/?#]+)", str(url or ""), re.I)
    if not match:
        return ""
    return unquote(match.group(1)).strip().rstrip("/").lower()


def _person_tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", str(text or "").lower()) if len(t) > 1 and t not in _NAME_STOP]


def _token_hit(token: str, parts: list[str]) -> bool:
    for part in parts:
        if part == token:
            return True
        if len(token) >= 3 and (part.startswith(token) or token.startswith(part)):
            return True
    return False


def _name_matches(stored: str, query: str) -> bool:
    want = _person_tokens(query)
    have = _person_tokens(stored)
    if not want or not have:
        return False
    return all(_token_hit(token, have) for token in want)


def _field_matches(stored: str, query: str, *, required: bool) -> bool:
    want = _person_tokens(query)
    if not want:
        return True
    have = _person_tokens(stored)
    if not have:
        return not required
    return all(_token_hit(token, have) for token in want)


def _person_emails(row: dict[str, Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    def add(raw: Any) -> None:
        text = str(raw or "").strip().lower()
        if not text or "@" not in text or text in seen:
            return
        seen.add(text)
        out.append(text)

    add(row.get("email"))
    for item in row.get("emails") or []:
        add(item.get("value") if isinstance(item, dict) else item)
    profile = row.get("profile") if isinstance(row.get("profile"), dict) else {}
    add(profile.get("email"))
    for item in profile.get("email_entries") or []:
        add(item.get("value") if isinstance(item, dict) else item)
    for item in profile.get("emails") or []:
        add(item.get("value") if isinstance(item, dict) else item)
    return out


def _is_scraped_person(row: dict[str, Any]) -> bool:
    if not isinstance(row, dict):
        return False
    if not _li_slug(str(row.get("linkedin_url") or "")):
        profile = row.get("profile") if isinstance(row.get("profile"), dict) else {}
        if not _li_slug(str(profile.get("linkedin_profile_url") or profile.get("url") or "")):
            return False
    name = str(row.get("name") or "").strip()
    if not name:
        profile = row.get("profile") if isinstance(row.get("profile"), dict) else {}
        name = str(profile.get("name") or "").strip()
    return bool(name)


def list_people() -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    if PEOPLE_DIR.exists():
        for path in PEOPLE_DIR.glob("*.json"):
            data = _read_json(path)
            if isinstance(data, dict) and data.get("key"):
                by_key[str(data["key"])] = data
    client = _sb()
    if client is not None:
        try:
            res = client.table("people").select("*").execute()
            for row in res.data or []:
                if isinstance(row, dict) and row.get("key"):
                    by_key[str(row["key"])] = row
        except Exception:
            pass
    return list(by_key.values())


def find_person_by_url(url: str) -> dict[str, Any] | None:
    slug = _li_slug(url)
    if not slug:
        return None
    candidates = [
        str(url or "").split("?")[0].rstrip("/"),
        f"https://www.linkedin.com/in/{slug}",
        f"https://linkedin.com/in/{slug}",
        f"https://www.linkedin.com/in/{slug}/",
    ]
    for candidate in candidates:
        rec = get_person(person_key(candidate, "", ""))
        if rec:
            return rec
    for row in list_people():
        profile = row.get("profile") if isinstance(row.get("profile"), dict) else {}
        blob = " ".join(
            str(x or "")
            for x in (
                row.get("linkedin_url"),
                profile.get("linkedin_profile_url"),
                profile.get("url"),
            )
        )
        if _li_slug(blob) == slug:
            return row
    return None


def find_people_for_query(
    *,
    url: str = "",
    name: str = "",
    company: str = "",
    email: str = "",
    role: str = "",
    location: str = "",
) -> list[dict[str, Any]]:
    url_text = str(url or "").strip()
    if _li_slug(url_text):
        hit = find_person_by_url(url_text)
        return [hit] if hit and _is_scraped_person(hit) else []
    email_n = str(email or "").strip().lower()
    name_q = str(name or "").strip()
    if "@" in name_q and not email_n:
        email_n = name_q.lower()
        name_q = ""
    name_tokens = _person_tokens(name_q)
    company_q = str(company or "").strip()
    if not email_n and not name_tokens:
        return []
    if len(name_tokens) < 2 and not email_n and not company_q:
        return []
    out: list[dict[str, Any]] = []
    for row in list_people():
        if not _is_scraped_person(row):
            continue
        profile = row.get("profile") if isinstance(row.get("profile"), dict) else {}
        if email_n and email_n not in _person_emails(row):
            continue
        stored_name = str(row.get("name") or profile.get("name") or "")
        if name_tokens and not _name_matches(stored_name, name_q):
            continue
        stored_company = str(row.get("company") or profile.get("current_company") or "")
        if company_q and not _field_matches(stored_company, company_q, required=True):
            continue
        stored_role = str(profile.get("current_role") or profile.get("role") or "")
        if not _field_matches(stored_role, role, required=False):
            continue
        stored_location = str(profile.get("location") or "")
        if not _field_matches(stored_location, location, required=False):
            continue
        out.append(row)
    return out


def person_to_profile(row: dict[str, Any]) -> dict[str, Any]:
    profile = row.get("profile") if isinstance(row.get("profile"), dict) else {}
    url = str(
        row.get("linkedin_url")
        or profile.get("linkedin_profile_url")
        or profile.get("url")
        or ""
    ).strip()
    email_entries = profile.get("email_entries") if isinstance(profile.get("email_entries"), list) else []
    phone_entries = profile.get("phone_entries") if isinstance(profile.get("phone_entries"), list) else []
    company_email_entries = profile.get("company_email_entries") if isinstance(profile.get("company_email_entries"), list) else []
    company_phone_entries = profile.get("company_phone_entries") if isinstance(profile.get("company_phone_entries"), list) else []
    emails = row.get("emails") if isinstance(row.get("emails"), list) else profile.get("emails")
    phones = row.get("phones") if isinstance(row.get("phones"), list) else profile.get("phones")
    if not isinstance(emails, list):
        emails = [item.get("value") for item in email_entries if isinstance(item, dict) and item.get("value")]
    if not isinstance(phones, list):
        phones = [item.get("value") for item in phone_entries if isinstance(item, dict) and item.get("value")]
    company_emails = profile.get("company_emails") if isinstance(profile.get("company_emails"), list) else [
        item.get("value") for item in company_email_entries if isinstance(item, dict) and item.get("value")
    ]
    company_phones = profile.get("company_phones") if isinstance(profile.get("company_phones"), list) else [
        item.get("value") for item in company_phone_entries if isinstance(item, dict) and item.get("value")
    ]
    return {
        "url": url,
        "linkedin_profile_url": url.split("?")[0] if url else "",
        "name": row.get("name") or profile.get("name"),
        "headline": profile.get("headline"),
        "current_role": profile.get("current_role") or profile.get("role"),
        "current_company": row.get("company") or profile.get("current_company"),
        "location": profile.get("location"),
        "about": profile.get("about"),
        "email": row.get("email") or profile.get("email"),
        "phone": row.get("phone") or profile.get("phone"),
        "emails": emails or [],
        "phones": phones or [],
        "email_entries": email_entries,
        "phone_entries": phone_entries,
        "company_emails": company_emails or [],
        "company_phones": company_phones or [],
        "company_email_entries": company_email_entries,
        "company_phone_entries": company_phone_entries,
        "links": profile.get("links") if isinstance(profile.get("links"), list) else [],
        "twitter": profile.get("twitter"),
        "other_channels": profile.get("other_channels") if isinstance(profile.get("other_channels"), list) else [],
        "photo": None,
        "banner": None,
        "error": None,
        "from_cache": True,
    }


def _contact_entry_key(value: str, kind: str) -> str:
    text = str(value or "").strip()
    if kind == "phone":
        return re.sub(r"\D", "", text)
    return text.lower()


def _as_contact_entries(items: Any, kind: str, *, allow_company_phone: bool = False) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items or []:
        value = str(item.get("value") or "").strip().rstrip("\\") if isinstance(item, dict) else str(item or "").strip().rstrip("\\")
        if isinstance(item, dict):
            src = str(item.get("source") or "").strip().lower()
        else:
            src = "saved"
        if src in ("guessed", "guess"):
            continue
        if kind == "phone" and src == "company_site" and not allow_company_phone:
            continue
        if kind == "phone":
            if value.count(".") > 1 or re.search(r"[A-Za-z]", value):
                continue
            digits = re.sub(r"\D", "", value)
            if len(digits) < 10 or len(digits) > 15:
                continue
        key = _contact_entry_key(value, kind)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append({"value": value, "source": src or "saved"})
    return out


def _merge_contact_entries(prev: Any, incoming: Any, kind: str, *, allow_company_phone: bool = False) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in _as_contact_entries(incoming, kind, allow_company_phone=allow_company_phone) + _as_contact_entries(
        prev, kind, allow_company_phone=allow_company_phone
    ):
        key = _contact_entry_key(item.get("value") or "", kind)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def upsert_person(record: dict[str, Any]) -> dict[str, Any]:
    key = person_key(
        record.get("linkedin_url") or record.get("linkedin_profile_url") or record.get("url") or "",
        record.get("name") or "",
        record.get("company") or record.get("current_company") or "",
    )
    prev = get_person(key) or {}
    prev_profile = prev.get("profile") if isinstance(prev.get("profile"), dict) else {}
    new_profile = record.get("profile") if isinstance(record.get("profile"), dict) else {}
    prev_emails = prev_profile.get("email_entries") or prev.get("emails") or []
    prev_phones = prev_profile.get("phone_entries") or prev.get("phones") or []
    email_entries = _merge_contact_entries(
        prev_emails,
        new_profile.get("email_entries") or record.get("emails") or [],
        "email",
    )
    phone_entries = _merge_contact_entries(
        prev_phones,
        new_profile.get("phone_entries") or record.get("phones") or [],
        "phone",
    )
    company_email_entries = _merge_contact_entries(
        prev_profile.get("company_email_entries") or [],
        new_profile.get("company_email_entries") or record.get("company_emails") or [],
        "email",
    )
    company_phone_entries = _merge_contact_entries(
        prev_profile.get("company_phone_entries") or [],
        new_profile.get("company_phone_entries") or record.get("company_phones") or [],
        "phone",
        allow_company_phone=True,
    )
    emails = [item["value"] for item in email_entries]
    phones = [item["value"] for item in phone_entries]
    sources = list(dict.fromkeys(item["source"] for item in email_entries + phone_entries if item.get("source")))
    email = str(record.get("email") or prev.get("email") or (emails[0] if emails else "") or "").strip().rstrip("\\") or None
    phone = str(record.get("phone") or prev.get("phone") or (phones[0] if phones else "") or "").strip().rstrip("\\") or None
    if phone and (phone.count(".") > 1 or re.search(r"[A-Za-z]", phone) or not (10 <= len(re.sub(r"\D", "", phone)) <= 15)):
        phone = phones[0] if phones else None
    profile = dict(prev_profile)
    for key, value in new_profile.items():
        if value in (None, "", []):
            continue
        profile[key] = value
    profile.pop("guessed_emails", None)
    profile.pop("photo", None)
    profile.pop("banner", None)
    profile.pop("shot", None)
    profile["email_entries"] = email_entries
    profile["phone_entries"] = phone_entries
    profile["company_email_entries"] = company_email_entries
    profile["company_phone_entries"] = company_phone_entries
    payload = {
        "key": key,
        "linkedin_url": str(record.get("linkedin_url") or record.get("linkedin_profile_url") or prev.get("linkedin_url") or "").strip() or None,
        "name": str(record.get("name") or prev.get("name") or "").strip() or None,
        "company": str(record.get("company") or record.get("current_company") or prev.get("company") or "").strip() or None,
        "email": email,
        "phone": phone,
        "emails": _jsonable(emails),
        "phones": _jsonable(phones),
        "sources": _jsonable(sources),
        "profile": _jsonable(profile),
        "updated_at": _now_iso(),
    }
    client = _sb()
    if client is None:
        _write_json(_person_path(key), payload)
        return payload
    try:
        client.table("people").upsert(payload).execute()
    except Exception:
        _write_json(_person_path(key), payload)
    return payload

