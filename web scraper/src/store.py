from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.paths import BOOKMARKS_PATH, CACHE, COMPANY_DIR, NEWS_DIR, WORKSPACE_PATH, company_key, ensure_dirs

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
    path = cache_path(source, key)
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
    path = cache_path(source, key)
    path.write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")
    client = _sb()
    if client is None:
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
    path = news_day_path(ckey, d)
    data = _read_json(path)
    if isinstance(data, dict) and news_is_fresh(data.get("fetched_at") or d):
        return data
    if path.exists():
        path.unlink()
    return None


def save_news_day(ckey: str, data: dict[str, Any], day: str | None = None) -> Path:
    d = day or datetime.now(timezone.utc).date().isoformat()
    path = news_day_path(ckey, d)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
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


def _persist_company(key: str, dossier: dict[str, Any], updated_at: float | None = None, disk: bool = True) -> None:
    dossier, _ = _ensure_dossier_summary(dossier)
    if disk:
        ensure_dirs()
        path = COMPANY_DIR / f"{key}.json"
        _write_json(path, dossier)
    resolved = dossier.get("resolved") or {}
    client = _sb()
    if client is None:
        return
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


def put_company(key: str, dossier: dict[str, Any], *, disk: bool = True) -> None:
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
                .execute()
            )
            out = []
            for row in res.data or []:
                if not isinstance(row.get("dossier"), dict):
                    continue
                dossier, changed = expire_dossier_news(row["dossier"])
                dossier, filled = _ensure_dossier_summary(dossier)
                rec = {
                    "key": row.get("key") or "",
                    "dossier": dossier,
                    "updated_at": _parse_ts(row.get("updated_at")),
                }
                if (changed or filled) and rec["key"]:
                    _persist_company(rec["key"], dossier, rec["updated_at"], disk=False)
                out.append(rec)
            if out:
                purge_stale_news()
                return out
        except Exception:
            pass
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
    local = _local_bookmark_keys()
    if k not in local:
        local.append(k)
        _write_local_bookmarks(local)
    client = _sb()
    if client is None:
        return
    try:
        client.table("bookmarks").upsert({"company_key": k, "created_at": _now_iso()}).execute()
    except Exception:
        pass


def remove_bookmark(key: str) -> None:
    k = str(key or "").strip()
    if not k:
        return
    _write_local_bookmarks([x for x in _local_bookmark_keys() if x != k])
    client = _sb()
    if client is None:
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
    client = _sb()
    if client is not None:
        try:
            res = client.table("bookmarks").select("company_key").order("created_at").execute()
            keys = [str(r.get("company_key") or "").strip() for r in (res.data or []) if str(r.get("company_key") or "").strip()]
            if keys:
                _write_local_bookmarks(keys)
                return keys
        except Exception:
            pass
        _migrate_workspace_bookmarks()
        try:
            res = client.table("bookmarks").select("company_key").order("created_at").execute()
            keys = [str(r.get("company_key") or "").strip() for r in (res.data or []) if str(r.get("company_key") or "").strip()]
            if keys:
                _write_local_bookmarks(keys)
                return keys
        except Exception:
            pass
    local = _local_bookmark_keys()
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


def put_workspace(bookmarks: list, leads: list, linkedin: dict) -> None:
    payload = {
        "leads": leads if isinstance(leads, list) else [],
        "linkedin": linkedin if isinstance(linkedin, dict) else {},
    }
    WORKSPACE_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = _read_json(WORKSPACE_PATH)
    disk = existing if isinstance(existing, dict) else {}
    disk["leads"] = payload["leads"]
    disk["linkedin"] = payload["linkedin"]
    _write_json(WORKSPACE_PATH, disk)
    client = _sb()
    if client is None:
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
