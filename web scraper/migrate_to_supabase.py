from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(REPO / "not to share" / ".env")

from src.paths import CACHE, COMPANY_DIR, LASTRUN, NEWS_DIR, RAW_DIR, WORKSPACE_PATH, company_key, ensure_dirs
from src.store import _jsonable, _now_iso, _sb, _safe_key


def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _iso_mtime(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    except Exception:
        return _now_iso()


def main() -> int:
    client = _sb()
    if client is None:
        return 1
    ensure_dirs()
    companies = 0
    if COMPANY_DIR.exists():
        for path in COMPANY_DIR.glob("*.json"):
            data = _read(path)
            if not isinstance(data, dict):
                continue
            key = company_key(str(data.get("query") or path.stem))
            resolved = data.get("resolved") or {}
            client.table("companies").upsert(
                {
                    "key": key,
                    "query": data.get("query") or key,
                    "ticker": resolved.get("ticker"),
                    "name": resolved.get("name") or (data.get("overview") or {}).get("legal_name"),
                    "dossier": _jsonable(data),
                    "updated_at": _iso_mtime(path),
                }
            ).execute()
            companies += 1
    caches = 0
    if CACHE.exists():
        for path in CACHE.rglob("*.json"):
            if not path.is_file():
                continue
            payload = _read(path)
            if payload is None:
                continue
            rel = path.relative_to(CACHE)
            if len(rel.parts) == 1:
                source = "_root"
                cache_key = path.stem
            else:
                source = rel.parts[0]
                cache_key = path.stem
            if isinstance(payload, dict) and "data" in payload:
                data = payload.get("data")
                fetched_at = payload.get("fetched_at") or _iso_mtime(path)
            else:
                data = payload
                fetched_at = _iso_mtime(path)
            client.table("source_cache").upsert(
                {
                    "source": source,
                    "cache_key": _safe_key(cache_key),
                    "data": _jsonable(data),
                    "fetched_at": fetched_at,
                }
            ).execute()
            caches += 1
    news = 0
    if NEWS_DIR.exists():
        for path in NEWS_DIR.rglob("*.json"):
            if not path.is_file():
                continue
            data = _read(path)
            if not isinstance(data, dict):
                continue
            ckey = path.parent.name
            day = path.stem
            client.table("news_days").upsert(
                {
                    "company_key": ckey,
                    "day": day,
                    "data": _jsonable(data),
                }
            ).execute()
            news += 1
    workspace = 0
    ws = _read(WORKSPACE_PATH)
    if isinstance(ws, dict):
        client.table("workspace").upsert(
            {
                "id": 1,
                "bookmarks": _jsonable(ws.get("bookmarks") if isinstance(ws.get("bookmarks"), list) else []),
                "leads": _jsonable(ws.get("leads") if isinstance(ws.get("leads"), list) else []),
                "linkedin": _jsonable(ws.get("linkedin") if isinstance(ws.get("linkedin"), dict) else {}),
                "updated_at": _now_iso(),
            }
        ).execute()
        workspace = 1
    db_companies = client.table("companies").select("key").execute()
    if companies and len(db_companies.data or []) < companies:
        return 2
    for folder in (COMPANY_DIR, CACHE, NEWS_DIR, RAW_DIR):
        if folder.exists():
            shutil.rmtree(folder)
    for extra in (LASTRUN, WORKSPACE_PATH, PRIVATE_MIGRATE):
        if extra.exists():
            extra.unlink()
    ensure_dirs()
    return 0


PRIVATE_MIGRATE = REPO / "not to share" / "web scraper" / "migrate_result.json"

if __name__ == "__main__":
    raise SystemExit(main())
