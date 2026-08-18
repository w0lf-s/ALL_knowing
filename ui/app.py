import asyncio
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECRETS = ROOT / "not to share"
VENV_PYTHON = SECRETS / ".venv" / "Scripts" / "python.exe"
LEAD_FINDER_DIR = ROOT / "lead finder"

from dotenv import load_dotenv

load_dotenv(SECRETS / ".env")

from flask import Flask, Response, jsonify, request, send_from_directory, stream_with_context

app = Flask(__name__)

sys.path.insert(0, str(ROOT / "web scraper"))
FRONT_DIR = ROOT / "front"


@app.route("/")
@app.route("/lead")
@app.route("/company")
@app.route("/linkedin")
@app.route("/people")
@app.route("/dashboard")
def index():
    return send_from_directory(str(FRONT_DIR), "index.html")


@app.route("/css/<path:subpath>")
def serve_css(subpath):
    return send_from_directory(str(FRONT_DIR / "css"), subpath)


@app.route("/js/<path:subpath>")
def serve_js(subpath):
    return send_from_directory(str(FRONT_DIR / "js"), subpath)


def _json_error(message: str, status: int = 400):
    return jsonify({"ok": False, "error": message}), status


def _friendly_cli_error(stderr: str, stdout: str, fallback: str) -> str:
    blob = "\n".join(part for part in (stderr, stdout) if part).strip()
    low = blob.lower()
    if any(
        token in low
        for token in (
            "navigating to",
            "waiting until",
            "timeout",
            "exceeded",
            "net::err",
        )
    ):
        return "LinkedIn took too long to load. Try again."
    if "target closed" in low or "browser has been closed" in low:
        return "The LinkedIn browser closed before search finished. Try again."
    if "auth" in low and ("required" in low or "checkpoint" in low or "login" in low):
        return "LinkedIn needs a login. Sign in with the saved session and try again."
    for line in reversed(blob.splitlines()):
        text = line.strip()
        if not text:
            continue
        if text.startswith("=") or text.startswith("- ") or text.startswith("File "):
            continue
        if text.lower().startswith("traceback") or "waiting until" in text.lower():
            continue
        if "navigating to" in text.lower():
            continue
        if len(text) > 8:
            return text[:280]
    return fallback


def _last_json_line(stdout: str):
    lines = [ln for ln in (stdout or "").splitlines() if ln.strip()]
    if not lines:
        return None
    return json.loads(lines[-1])


def _people_hints(data: dict | None) -> dict:
    src = data if isinstance(data, dict) else {}
    nested = src.get("hints") if isinstance(src.get("hints"), dict) else {}
    out = {}
    for key in ("name", "company", "role", "title", "location", "email", "phone"):
        val = str(nested.get(key) or src.get(key) or "").strip()
        if not val:
            continue
        out["role" if key == "title" else key] = val
    return out


def _people_from_store(
    *,
    url: str = "",
    name: str = "",
    company: str = "",
    title: str = "",
    location: str = "",
    email: str = "",
) -> list[dict]:
    try:
        from src.store import find_people_for_query, person_to_profile

        rows = find_people_for_query(
            url=url,
            name=name,
            company=company,
            email=email,
            role=title,
            location=location,
        )
    except Exception:
        return []
    out = []
    for row in rows:
        try:
            out.append(person_to_profile(row))
        except Exception:
            continue
    return out


def _kill_process_tree(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                timeout=10,
            )
        else:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


_LI_RUNNER = """
import json, sys
sys.path.insert(0, r"{li_root}")
from src.config import get_settings, ensure_dirs
from src.scraper import run
ensure_dirs()
raw = sys.argv[1]
try:
    parsed = json.loads(raw)
    if isinstance(parsed, list):
        urls = [str(u).strip() for u in parsed if str(u).strip()]
    elif isinstance(parsed, str) and parsed.strip():
        urls = [parsed.strip()]
    else:
        urls = []
except Exception:
    urls = [u.strip() for u in raw.replace(",", "\\n").splitlines() if u.strip()]
hints = {{}}
if len(sys.argv) > 2:
    try:
        parsed_hints = json.loads(sys.argv[2])
        if isinstance(parsed_hints, dict):
            hints = parsed_hints
    except Exception:
        hints = {{}}
if not urls:
    print("[]")
    raise SystemExit(0)
settings = get_settings()
settings.headless = True
settings.checkpoint_timeout_seconds = min(settings.checkpoint_timeout_seconds, 20)
settings.delay_min_seconds = min(settings.delay_min_seconds, 0.6)
settings.delay_max_seconds = min(settings.delay_max_seconds, 1.2)
def _emit(obj):
    print(json.dumps(obj, default=str), flush=True)
rows = run(settings, on_progress=_emit, urls=urls, hints=hints)
print(json.dumps(rows or [], default=str), flush=True)
"""

_LEAD_PARSE = """
import json, sys
sys.path.insert(0, r"{lf_root}")
from src.cookie_parse import primary_email_from_cookie_file
from src.email_parse import classify_email
from pathlib import Path
email = sys.argv[1]
cookie = sys.argv[2] if len(sys.argv) > 2 else ""
if cookie:
    email = primary_email_from_cookie_file(Path(cookie))
print(json.dumps({{"email": email, "parsed": classify_email(email).to_dict()}}))
"""

_LEAD_INVESTIGATE = """
import json, sys
sys.path.insert(0, r"{lf_root}")
from src.cookie_parse import primary_email_from_cookie_file
from src.orchestrate import run_lead_finder
from pathlib import Path
email = sys.argv[1]
cookie = sys.argv[2] if len(sys.argv) > 2 else ""
max_profiles = int(sys.argv[3]) if len(sys.argv) > 3 else 5
if cookie:
    email = primary_email_from_cookie_file(Path(cookie))
result = run_lead_finder(
    email,
    max_profiles=max_profiles,
    headless=True,
    live=False,
    no_scrape=True,
    no_search=True,
)
print(json.dumps(result, default=str))
"""

_LI_SEARCH = """
import json, sys
sys.path.insert(0, r"{lf_root}")
from src.linkedin_search import search_people_urls
name = sys.argv[1]
company = sys.argv[2] if len(sys.argv) > 2 else ""
max_profiles = int(sys.argv[3]) if len(sys.argv) > 3 else 5
title = sys.argv[4] if len(sys.argv) > 4 else ""
location = sys.argv[5] if len(sys.argv) > 5 else ""
def _emit(obj):
    print(json.dumps(obj, default=str), flush=True)
try:
    found = search_people_urls(name, company, title=title, location=location, max_profiles=max_profiles, headless=True, on_progress=_emit)
    urls = [c.get("url") for c in (found or []) if isinstance(c, dict) and c.get("url")]
    _emit({{"done": True, "ok": True, "candidates": found or [], "candidate_urls": urls}})
except Exception as exc:
    _emit({{"done": True, "error": str(exc)}})
    raise SystemExit(1)
"""

_LI_ENRICH = """
import json, sys
sys.path.insert(0, r"{li_root}")
from src.contacts import enrich_profile
row = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {{}}
hints = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {{}}
if not isinstance(row, dict):
    row = {{}}
if not isinstance(hints, dict):
    hints = {{}}
print(json.dumps(enrich_profile(row, hints=hints), default=str))
"""

_LEAD_SAMPLES = """
import json, sys
sys.path.insert(0, r"{lf_root}")
from src.cookie_parse import load_sample_leads
print(json.dumps(load_sample_leads(), default=str))
"""


@app.get("/api/lead/samples")
def api_lead_samples():
    try:
        script = _LEAD_SAMPLES.format(
            lf_root=str(LEAD_FINDER_DIR).replace("\\", "\\\\")
        )
        proc = subprocess.run(
            [str(VENV_PYTHON), "-c", script],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(LEAD_FINDER_DIR),
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            return _json_error(err.splitlines()[-1] if err else "Failed to load samples")
        samples = _last_json_line(proc.stdout) or []
        return jsonify({"ok": True, "samples": samples})
    except Exception as exc:
        return _json_error(str(exc))


@app.post("/api/lead/parse")
def api_lead_parse():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email") or "").strip()
    if not email:
        return _json_error("Enter an email")
    try:
        script = _LEAD_PARSE.format(lf_root=str(LEAD_FINDER_DIR).replace("\\", "\\\\"))
        proc = subprocess.run(
            [str(VENV_PYTHON), "-c", script, email, ""],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(LEAD_FINDER_DIR),
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            return _json_error(err.splitlines()[-1] if err else "Lead parse failed")
        payload = _last_json_line(proc.stdout)
        if not payload:
            return _json_error("Lead parse returned no output")
        return jsonify({"ok": True, **payload})
    except Exception as exc:
        return _json_error(str(exc))


@app.post("/api/lead/investigate")
def api_lead_investigate():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email") or "").strip()
    max_profiles = int(data.get("max_profiles") or 5)
    if not email:
        return _json_error("Enter an email")
    try:
        script = _LEAD_INVESTIGATE.format(
            lf_root=str(LEAD_FINDER_DIR).replace("\\", "\\\\")
        )
        global _lead_investigation_proc
        with _lead_investigation_lock:
            if _lead_investigation_proc is not None and _lead_investigation_proc.poll() is None:
                _kill_process_tree(_lead_investigation_proc)
            _lead_investigation_proc = subprocess.Popen(
                [
                    str(VENV_PYTHON),
                    "-c",
                    script,
                    email,
                    "",
                    str(max(1, min(max_profiles, 10))),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=str(LEAD_FINDER_DIR),
                env={**os.environ, "HEADLESS": "true"},
            )

        proc = _lead_investigation_proc
        try:
            stdout, stderr = proc.communicate(timeout=150)
        except subprocess.TimeoutExpired:
            _kill_process_tree(proc)
            with _lead_investigation_lock:
                if _lead_investigation_proc is proc:
                    _lead_investigation_proc = None
            return _json_error("Lead investigation timed out", 504)
        finally:
            with _lead_investigation_lock:
                if _lead_investigation_proc is proc:
                    _lead_investigation_proc = None

        if proc.returncode != 0:
            err = (stderr or stdout or "").strip()
            return _json_error(
                err.splitlines()[-1] if err else "Lead investigation failed"
            )

        result = _last_json_line(stdout)
        if not result:
            return _json_error("Lead investigation returned no output")
        return jsonify({"ok": True, "result": result})
    except Exception as exc:
        return _json_error(str(exc))


@app.post("/api/company/news")
def api_company_news():
    data = request.get_json(silent=True) or {}
    query = str(data.get("query") or "").strip()
    if not query:
        return _json_error("Enter a company name")
    try:
        from src.pipeline import fetch_company_news

        payload = asyncio.run(fetch_company_news(query, use_groq=True, use_playwright=True))
        return jsonify({"ok": True, **payload})
    except Exception as exc:
        return _json_error(str(exc))


@app.post("/api/company")
def api_company():
    data = request.get_json(silent=True) or {}
    query = str(data.get("query") or "").strip()
    fast = bool(data.get("fast", False))
    if not query:
        return _json_error("Enter a company name")
    try:
        from src.pipeline import run_pipeline

        dossier = asyncio.run(run_pipeline(
            query,
            use_groq=not fast,
            use_playwright=not fast,
        ))
        return jsonify({"ok": True, "dossier": dossier.model_dump()})
    except Exception as exc:
        return _json_error(str(exc))


import queue
import threading

_progress_queues: dict[str, queue.Queue] = {}

_lead_investigation_lock = threading.Lock()
_lead_investigation_proc: subprocess.Popen | None = None
_linkedin_scrape_lock = threading.Lock()
_linkedin_scrape_proc: subprocess.Popen | None = None
_linkedin_search_lock = threading.Lock()
_linkedin_search_proc: subprocess.Popen | None = None


@app.post("/api/lead/investigate/stop")
def api_lead_investigate_stop():
    global _lead_investigation_proc
    with _lead_investigation_lock:
        if _lead_investigation_proc is None or _lead_investigation_proc.poll() is not None:
            return jsonify({"ok": True})
        _kill_process_tree(_lead_investigation_proc)
    return jsonify({"ok": True})


def _fresh_company_dossier(query: str, max_age_s: float = 6 * 3600):
    from src.store import find_company_record

    rec = find_company_record(query)
    if not rec:
        return None
    if time.time() - rec["updated_at"] > max_age_s:
        return None
    data = rec["dossier"]
    ticker = ((data.get("resolved") or {}).get("ticker") or "")
    fin = data.get("financials") or {}
    overview = data.get("overview") or {}
    desc = str(overview.get("description") or "")
    short = str(overview.get("short_description") or "").lower()
    if re.search(r"\bmay refer to\b", desc, re.I) or "same term" in short or "disambiguation" in short:
        return None
    if re.match(rf"^an?\s+{re.escape(query.strip())}\s+is\b", desc, re.I):
        return None
    skip = {"highlights", "via", "metrics_raw"}
    has_fin = any(k not in skip and v not in (None, "", []) for k, v in fin.items())
    if not ticker or len(ticker.split(".")[0]) > 5 or not has_fin:
        return None
    return data


@app.get("/api/company/stream")
def api_company_stream():
    query = request.args.get("query", "").strip()
    fast = request.args.get("fast", "0") == "1"
    if not query:
        return _json_error("Enter a company name")

    stream_id = f"{query}_{id(request)}"
    q: queue.Queue = queue.Queue()
    _progress_queues[stream_id] = q

    def progress_cb(pct, step):
        q.put({"pct": pct, "step": step})

    def run():
        try:
            cached = _fresh_company_dossier(query)
            if cached:
                q.put({"pct": 40, "step": "Loading cached dossier"})
                q.put({"pct": 100, "step": "Complete", "done": True, "ok": True})
                return
            from src.pipeline import run_pipeline, set_progress_callback
            set_progress_callback(progress_cb)
            asyncio.run(run_pipeline(
                query,
                use_groq=not fast,
                use_playwright=not fast,
            ))
            q.put({"pct": 100, "step": "Complete", "done": True, "ok": True})
        except Exception as exc:
            q.put({"pct": 100, "step": "Failed", "done": True, "error": str(exc)})
        finally:
            from src.pipeline import set_progress_callback
            set_progress_callback(None)

    t = threading.Thread(target=run, daemon=True)
    t.start()

    def generate():
        while True:
            try:
                msg = q.get(timeout=120)
            except queue.Empty:
                yield f"data: {json.dumps({'pct': 100, 'step': 'Timeout', 'done': True, 'error': 'Pipeline timed out'})}\n\n"
                break
            yield f"data: {json.dumps(msg, default=str)}\n\n"
            if msg.get("done"):
                break
        _progress_queues.pop(stream_id, None)

    return Response(generate(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


_bookmark_refresh_lock = threading.Lock()
_bookmark_refreshing: set[str] = set()
_BOOKMARK_MAX_AGE_S = 24 * 3600


def _find_company_record(query: str):
    from src.store import find_company_record

    return find_company_record(query)


def _refresh_bookmarked_job(queries: list[str]):
    from src.pipeline import run_pipeline

    for query in queries:
        try:
            rec = _find_company_record(query)
            run_q = query
            prev = rec["dossier"] if rec else None
            if prev and prev.get("query"):
                run_q = str(prev["query"])
            asyncio.run(
                run_pipeline(
                    run_q,
                    use_groq=False,
                    use_playwright=False,
                    skip_news=True,
                    lite=True,
                )
            )
        except Exception:
            pass
        finally:
            with _bookmark_refresh_lock:
                _bookmark_refreshing.discard(str(query).lower().strip())


@app.post("/api/company/refresh")
def api_company_refresh():
    data = request.get_json(silent=True) or {}
    raw = data.get("queries") or []
    queries: list[str] = []
    seen: set[str] = set()
    for item in raw:
        q = str(item or "").strip()
        if not q:
            continue
        key = q.lower()
        if key in seen:
            continue
        seen.add(key)
        queries.append(q)
        if len(queries) >= 15:
            break
    reports = []
    stale = []
    now = time.time()
    for q in queries:
        rec = _find_company_record(q)
        existing = rec["dossier"] if rec else None
        if existing:
            reports.append(existing)
        fresh = bool(rec and (now - rec["updated_at"]) <= _BOOKMARK_MAX_AGE_S)
        if not fresh:
            stale.append(q)
    to_run: list[str] = []
    with _bookmark_refresh_lock:
        for q in stale:
            key = q.lower().strip()
            if key in _bookmark_refreshing:
                continue
            _bookmark_refreshing.add(key)
            to_run.append(q)
    if to_run:
        threading.Thread(target=_refresh_bookmarked_job, args=(to_run,), daemon=True).start()
    return jsonify({"ok": True, "reports": reports, "refreshing": to_run})


@app.post("/api/linkedin")
def api_linkedin():
    data = request.get_json(silent=True) or {}
    raw_urls = data.get("urls")
    if isinstance(raw_urls, list):
        urls = [str(u).strip() for u in raw_urls if str(u).strip()]
    else:
        url = str(data.get("url") or "").strip()
        urls = [url] if url else []
    urls = urls[:5]
    if not urls:
        return _json_error("Enter a profile URL")
    hints = _people_hints(data)
    try:
        script = _LI_RUNNER.format(
            li_root=str(ROOT / "lead scraper").replace("\\", "\\\\")
        )
        proc = subprocess.run(
            [str(VENV_PYTHON), "-c", script, json.dumps(urls), json.dumps(hints)],
            capture_output=True,
            text=True,
            timeout=min(300, 90 * max(1, len(urls))),
            cwd=str(ROOT / "lead scraper"),
            env={**os.environ, "HEADLESS": "true"},
        )
        if proc.returncode != 0:
            return _json_error(_friendly_cli_error(proc.stderr, proc.stdout, "Scraper failed"))
        payload = _last_json_line(proc.stdout)
        if isinstance(payload, list):
            profiles = payload
        elif isinstance(payload, dict):
            profiles = [payload] if payload else []
        else:
            profiles = []
        return jsonify({
            "ok": True,
            "profiles": profiles,
            "profile": profiles[0] if profiles else {},
        })
    except subprocess.TimeoutExpired:
        return _json_error("LinkedIn scraper timed out", 504)
    except Exception as exc:
        return _json_error(str(exc))


@app.route("/api/linkedin/stream", methods=["GET", "POST"])
def api_linkedin_stream():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        parsed = data.get("urls")
        hints = _people_hints(data)
        raw = json.dumps(parsed) if parsed is not None else "[]"
    else:
        raw = request.args.get("urls") or "[]"
        hints = {}
        try:
            parsed_hints = json.loads(request.args.get("hints") or "{}")
            if isinstance(parsed_hints, dict):
                hints = _people_hints(parsed_hints)
        except Exception:
            hints = {}
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = []
    if isinstance(parsed, list):
        urls = [str(u).strip() for u in parsed if str(u).strip()]
    elif isinstance(parsed, str) and parsed.strip():
        urls = [parsed.strip()]
    else:
        urls = []
    urls = urls[:5]
    if not urls:
        return _json_error("Enter a profile URL")

    script = _LI_RUNNER.format(
        li_root=str(ROOT / "lead scraper").replace("\\", "\\\\")
    )
    global _linkedin_scrape_proc
    with _linkedin_scrape_lock:
        if _linkedin_scrape_proc is not None and _linkedin_scrape_proc.poll() is None:
            _kill_process_tree(_linkedin_scrape_proc)
        proc = subprocess.Popen(
            [str(VENV_PYTHON), "-c", script, json.dumps(urls), json.dumps(hints)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(ROOT / "lead scraper"),
            env={**os.environ, "HEADLESS": "true", "PYTHONUNBUFFERED": "1"},
        )
        _linkedin_scrape_proc = proc

    def generate():
        global _linkedin_scrape_proc
        sent_done = False
        try:
            yield "retry: 3600000\n\n"
            assert proc.stdout is not None
            for line in proc.stdout:
                text = line.strip()
                if not text:
                    continue
                try:
                    msg = json.loads(text)
                except Exception:
                    continue
                if isinstance(msg, list):
                    sent_done = True
                    yield f"data: {json.dumps({'done': True, 'ok': True, 'profiles': msg}, default=str)}\n\n"
                elif isinstance(msg, dict):
                    if msg.get("done"):
                        sent_done = True
                    yield f"data: {json.dumps(msg, default=str)}\n\n"
            code = proc.wait(timeout=5)
            if not sent_done:
                sent_done = True
                if code not in (0, None):
                    err = (proc.stderr.read() if proc.stderr else "") or "People lookup failed"
                    yield f"data: {json.dumps({'done': True, 'error': err.strip().splitlines()[-1] if err.strip() else 'People lookup failed'})}\n\n"
                else:
                    yield f"data: {json.dumps({'done': True, 'ok': True})}\n\n"
        except Exception as exc:
            _kill_process_tree(proc)
            if not sent_done:
                sent_done = True
                yield f"data: {json.dumps({'done': True, 'error': str(exc)})}\n\n"
        finally:
            if proc.poll() is None:
                _kill_process_tree(proc)
            with _linkedin_scrape_lock:
                if _linkedin_scrape_proc is proc:
                    _linkedin_scrape_proc = None

    return Response(stream_with_context(generate()), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    })


@app.post("/api/linkedin/scrape/stop")
def api_linkedin_scrape_stop():
    global _linkedin_scrape_proc
    with _linkedin_scrape_lock:
        if _linkedin_scrape_proc is None or _linkedin_scrape_proc.poll() is not None:
            return jsonify({"ok": True})
        _kill_process_tree(_linkedin_scrape_proc)
        _linkedin_scrape_proc = None
    return jsonify({"ok": True})


@app.post("/api/linkedin/search/stop")
def api_linkedin_search_stop():
    global _linkedin_search_proc
    with _linkedin_search_lock:
        if _linkedin_search_proc is None or _linkedin_search_proc.poll() is not None:
            return jsonify({"ok": True})
        _kill_process_tree(_linkedin_search_proc)
        _linkedin_search_proc = None
    return jsonify({"ok": True})


@app.post("/api/linkedin/search")
def api_linkedin_search():
    global _linkedin_search_proc
    data = request.get_json(silent=True) or {}
    name = str(data.get("name") or data.get("query") or "").strip()
    company = str(data.get("company") or "").strip()
    title = str(data.get("title") or data.get("role") or "").strip()
    location = str(data.get("location") or "").strip()
    email = str(data.get("email") or "").strip()
    max_profiles = int(data.get("max_profiles") or 5)
    if not name:
        name = email
    if not name:
        return _json_error("Enter a name, email, or profile URL")
    stored = _people_from_store(
        name="" if "@" in name else name,
        company=company,
        title=title,
        location=location,
        email=email or (name if "@" in name else ""),
    )
    stored_urls = []
    seen_urls: set[str] = set()
    for row in stored:
        item = str(row.get("linkedin_profile_url") or row.get("url") or "").strip()
        key = item.split("?")[0].rstrip("/").lower()
        if "/in/" not in key or key in seen_urls:
            continue
        seen_urls.add(key)
        stored_urls.append(item)
    if stored and not stored_urls:
        def cached_search():
            yield "retry: 3600000\n\n"
            yield f"data: {json.dumps({'pct': 40, 'step': 'Loading saved profile...'})}\n\n"
            yield f"data: {json.dumps({'done': True, 'ok': True, 'cached': True, 'profiles': stored, 'candidates': []}, default=str)}\n\n"

        return Response(stream_with_context(cached_search()), mimetype="text/event-stream", headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        })
    if stored_urls:
        hints = _people_hints(data)
        script = _LI_RUNNER.format(
            li_root=str(ROOT / "lead scraper").replace("\\", "\\\\")
        )
        with _linkedin_search_lock:
            if _linkedin_search_proc is not None and _linkedin_search_proc.poll() is None:
                _kill_process_tree(_linkedin_search_proc)
            proc = subprocess.Popen(
                [str(VENV_PYTHON), "-c", script, json.dumps(stored_urls), json.dumps(hints)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                cwd=str(ROOT / "lead scraper"),
                env={**os.environ, "HEADLESS": "true", "PYTHONUNBUFFERED": "1"},
            )
            _linkedin_search_proc = proc

        def cached_visuals():
            global _linkedin_search_proc
            sent_done = False
            profiles = list(stored)
            try:
                yield "retry: 3600000\n\n"
                yield f"data: {json.dumps({'pct': 12, 'step': 'Loading saved profile...'})}\n\n"
                assert proc.stdout is not None
                for line in proc.stdout:
                    text = line.strip()
                    if not text:
                        continue
                    try:
                        msg = json.loads(text)
                    except Exception:
                        continue
                    if isinstance(msg, list):
                        sent_done = True
                        profiles = msg or profiles
                        yield f"data: {json.dumps({'done': True, 'ok': True, 'cached': True, 'profiles': profiles, 'candidates': []}, default=str)}\n\n"
                    elif isinstance(msg, dict):
                        if msg.get("step"):
                            yield f"data: {json.dumps({'pct': msg.get('pct') or 0, 'step': msg.get('step')}, default=str)}\n\n"
                        if isinstance(msg.get("profile"), dict):
                            row = msg["profile"]
                            key = str(row.get("linkedin_profile_url") or row.get("url") or "").split("?")[0].rstrip("/").lower()
                            replaced = False
                            for i, prev in enumerate(profiles):
                                prev_key = str(prev.get("linkedin_profile_url") or prev.get("url") or "").split("?")[0].rstrip("/").lower()
                                if key and prev_key == key:
                                    profiles[i] = row
                                    replaced = True
                                    break
                            if not replaced:
                                profiles.append(row)
                        if msg.get("done"):
                            sent_done = True
                            if isinstance(msg.get("profiles"), list) and msg.get("profiles"):
                                profiles = msg["profiles"]
                            yield f"data: {json.dumps({'done': True, 'ok': True, 'cached': True, 'profiles': profiles, 'candidates': []}, default=str)}\n\n"
                code = proc.wait(timeout=5)
                if not sent_done:
                    sent_done = True
                    with _linkedin_search_lock:
                        cancelled = _linkedin_search_proc is None
                    if cancelled:
                        yield f"data: {json.dumps({'done': True, 'ok': True, 'cancelled': True, 'candidates': [], 'profiles': []})}\n\n"
                    elif code not in (0, None):
                        yield f"data: {json.dumps({'done': True, 'ok': True, 'cached': True, 'profiles': profiles or stored, 'candidates': []}, default=str)}\n\n"
                    else:
                        yield f"data: {json.dumps({'done': True, 'ok': True, 'cached': True, 'profiles': profiles or stored, 'candidates': []}, default=str)}\n\n"
            except Exception as exc:
                _kill_process_tree(proc)
                if not sent_done:
                    yield f"data: {json.dumps({'done': True, 'ok': True, 'cached': True, 'profiles': stored, 'candidates': []}, default=str)}\n\n"
            finally:
                if proc.poll() is None:
                    _kill_process_tree(proc)
                with _linkedin_search_lock:
                    if _linkedin_search_proc is proc:
                        _linkedin_search_proc = None

        return Response(stream_with_context(cached_visuals()), mimetype="text/event-stream", headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        })
    script = _LI_SEARCH.format(
        lf_root=str(LEAD_FINDER_DIR).replace("\\", "\\\\")
    )
    with _linkedin_search_lock:
        if _linkedin_search_proc is not None and _linkedin_search_proc.poll() is None:
            _kill_process_tree(_linkedin_search_proc)
        proc = subprocess.Popen(
            [
                str(VENV_PYTHON),
                "-c",
                script,
                name,
                company,
                str(max(1, min(max_profiles, 10))),
                title,
                location,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd=str(LEAD_FINDER_DIR),
            env={**os.environ, "HEADLESS": "true", "PYTHONUNBUFFERED": "1"},
        )
        _linkedin_search_proc = proc

    def generate():
        global _linkedin_search_proc
        sent_done = False
        try:
            yield "retry: 3600000\n\n"
            assert proc.stdout is not None
            for line in proc.stdout:
                text = line.strip()
                if not text:
                    continue
                try:
                    msg = json.loads(text)
                except Exception:
                    continue
                if isinstance(msg, dict):
                    if msg.get("done"):
                        sent_done = True
                    yield f"data: {json.dumps(msg, default=str)}\n\n"
            code = proc.wait(timeout=5)
            if not sent_done:
                sent_done = True
                with _linkedin_search_lock:
                    cancelled = _linkedin_search_proc is None
                if cancelled:
                    yield f"data: {json.dumps({'done': True, 'ok': True, 'cancelled': True, 'candidates': []})}\n\n"
                elif code not in (0, None):
                    err = (proc.stderr.read() if proc.stderr else "") or ""
                    yield f"data: {json.dumps({'done': True, 'error': _friendly_cli_error(err, '', 'LinkedIn search failed')})}\n\n"
                else:
                    yield f"data: {json.dumps({'done': True, 'ok': True, 'candidates': []})}\n\n"
        except Exception as exc:
            _kill_process_tree(proc)
            if not sent_done:
                yield f"data: {json.dumps({'done': True, 'error': str(exc)})}\n\n"
        finally:
            if proc.poll() is None:
                _kill_process_tree(proc)
            with _linkedin_search_lock:
                if _linkedin_search_proc is proc:
                    _linkedin_search_proc = None

    return Response(stream_with_context(generate()), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    })


@app.post("/api/people/enrich")
def api_people_enrich():
    data = request.get_json(silent=True) or {}
    hints = _people_hints(data)
    if not any(hints.get(k) for k in ("name", "email", "company", "phone")):
        return _json_error("Enter a name, email, company, or phone")
    row = {
        "name": hints.get("name") or None,
        "current_company": hints.get("company") or None,
        "current_role": hints.get("role") or None,
        "location": hints.get("location") or None,
        "email": hints.get("email") or None,
        "phone": hints.get("phone") or None,
        "url": "",
        "linkedin_profile_url": "",
        "links": [],
        "error": None,
    }
    try:
        script = _LI_ENRICH.format(
            li_root=str(ROOT / "lead scraper").replace("\\", "\\\\")
        )
        proc = subprocess.run(
            [str(VENV_PYTHON), "-c", script, json.dumps(row), json.dumps(hints)],
            capture_output=True,
            text=True,
            timeout=90,
            cwd=str(ROOT / "lead scraper"),
            env={**os.environ},
        )
        if proc.returncode != 0:
            return _json_error(_friendly_cli_error(proc.stderr, proc.stdout, "Contact lookup failed"))
        payload = _last_json_line(proc.stdout)
        profile = payload if isinstance(payload, dict) else row
        return jsonify({"ok": True, "profile": profile})
    except subprocess.TimeoutExpired:
        return _json_error("Contact lookup timed out", 504)
    except Exception as exc:
        return _json_error(str(exc))


@app.get("/api/reports")
def api_reports():
    from src.store import list_companies

    return jsonify({"ok": True, "reports": list_companies()})


@app.get("/api/stats")
def api_stats():
    from src.store import list_companies

    reports = list_companies()
    return jsonify({
        "ok": True,
        "total_companies": len(reports),
    })


@app.get("/api/workspace")
def api_workspace_get():
    from src.store import get_workspace

    data = get_workspace()
    return jsonify({"ok": True, **data})


@app.put("/api/workspace")
def api_workspace_put():
    from src.store import put_workspace

    data = request.get_json(silent=True) or {}
    bookmarks = data.get("bookmarks") if isinstance(data.get("bookmarks"), list) else []
    leads = data.get("leads") if isinstance(data.get("leads"), list) else []
    linkedin = data.get("linkedin") if isinstance(data.get("linkedin"), dict) else {}
    put_workspace(bookmarks, leads, linkedin)
    return jsonify({"ok": True})


@app.get("/api/bookmarks")
def api_bookmarks_get():
    from src.store import list_bookmarks

    return jsonify({"ok": True, "bookmarks": list_bookmarks()})


@app.post("/api/bookmarks")
def api_bookmarks_add():
    from src.store import add_bookmark, list_bookmarks

    data = request.get_json(silent=True) or {}
    key = str(data.get("key") or "").strip()
    if not key:
        return _json_error("Missing company key")
    add_bookmark(key)
    return jsonify({"ok": True, "bookmarks": list_bookmarks()})


@app.delete("/api/bookmarks")
def api_bookmarks_remove():
    from src.store import list_bookmarks, remove_bookmark

    data = request.get_json(silent=True) or {}
    key = str(data.get("key") or request.args.get("key") or "").strip()
    if not key:
        return _json_error("Missing company key")
    remove_bookmark(key)
    return jsonify({"ok": True, "bookmarks": list_bookmarks()})


@app.route("/front/")
@app.route("/front/<path:subpath>")
def serve_front(subpath="index.html"):
    fp = FRONT_DIR / subpath
    if fp.exists() and fp.is_file():
        return send_from_directory(str(FRONT_DIR), subpath)
    return send_from_directory(str(FRONT_DIR), "index.html")


@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    return response


if __name__ == "__main__":
    app.run(debug=True, port=5000, threaded=True)
