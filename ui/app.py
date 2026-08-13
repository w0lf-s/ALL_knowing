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
COOKIES_DIR = SECRETS / "lead finder" / "cookies"

from dotenv import load_dotenv

load_dotenv(SECRETS / ".env")

from flask import Flask, Response, jsonify, render_template, request

app = Flask(__name__)

sys.path.insert(0, str(ROOT / "web scraper"))


@app.route("/")
@app.route("/lead")
@app.route("/company")
@app.route("/linkedin")
@app.route("/dashboard")
def index():
    from flask import send_from_directory
    return send_from_directory(str(FRONT_DIR), "index.html")


@app.route("/css/<path:subpath>")
def serve_css(subpath):
    from flask import send_from_directory
    return send_from_directory(str(FRONT_DIR / "css"), subpath)


@app.route("/js/<path:subpath>")
def serve_js(subpath):
    from flask import send_from_directory
    return send_from_directory(str(FRONT_DIR / "js"), subpath)


def _json_error(message: str, status: int = 400):
    return jsonify({"ok": False, "error": message}), status


def _last_json_line(stdout: str):
    lines = [ln for ln in (stdout or "").splitlines() if ln.strip()]
    if not lines:
        return None
    return json.loads(lines[-1])


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
from src.config import URLS_PATH, get_settings, ensure_dirs
from src.scraper import run
ensure_dirs()
URLS_PATH.parent.mkdir(parents=True, exist_ok=True)
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
if not urls:
    print("[]")
    raise SystemExit(0)
URLS_PATH.write_text("\\n".join(urls) + "\\n", encoding="utf-8")
settings = get_settings()
settings.headless = True
settings.checkpoint_timeout_seconds = min(settings.checkpoint_timeout_seconds, 20)
rows = run(settings)
print(json.dumps(rows or [], default=str))
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
)
print(json.dumps(result, default=str))
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


@app.post("/api/lead/investigate/stop")
def api_lead_investigate_stop():
    global _lead_investigation_proc
    with _lead_investigation_lock:
        if _lead_investigation_proc is None or _lead_investigation_proc.poll() is not None:
            return jsonify({"ok": True})
        _kill_process_tree(_lead_investigation_proc)
    return jsonify({"ok": True})


def _fresh_company_dossier(query: str, max_age_s: float = 6 * 3600):
    from src.paths import COMPANY_DIR, company_key

    path = COMPANY_DIR / f"{company_key(query)}.json"
    if not path.exists():
        return None
    if time.time() - path.stat().st_mtime > max_age_s:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
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


def _dossier_from_path(path):
    if path is None or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _query_matches_dossier(data: dict, query: str) -> bool:
    q = query.lower().strip()
    if not q or not isinstance(data, dict):
        return False
    from src.paths import company_key

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


def _find_company_file(query: str):
    from src.paths import COMPANY_DIR, company_key

    q = str(query or "").strip()
    if not q:
        return None
    direct = COMPANY_DIR / f"{company_key(q)}.json"
    if direct.exists():
        return direct
    if not COMPANY_DIR.exists():
        return None
    for path in COMPANY_DIR.glob("*.json"):
        data = _dossier_from_path(path)
        if data and _query_matches_dossier(data, q):
            return path
    return None


def _refresh_bookmarked_job(queries: list[str]):
    from src.pipeline import run_pipeline

    for query in queries:
        try:
            path = _find_company_file(query)
            run_q = query
            prev = _dossier_from_path(path) if path else None
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
        path = _find_company_file(q)
        existing = _dossier_from_path(path) if path else None
        if existing:
            reports.append(existing)
        fresh = bool(path and (now - path.stat().st_mtime) <= _BOOKMARK_MAX_AGE_S)
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
        return _json_error("Enter a LinkedIn profile URL")
    try:
        script = _LI_RUNNER.format(
            li_root=str(ROOT / "linkedin scrape").replace("\\", "\\\\")
        )
        proc = subprocess.run(
            [str(VENV_PYTHON), "-c", script, json.dumps(urls)],
            capture_output=True,
            text=True,
            timeout=min(300, 90 * max(1, len(urls))),
            cwd=str(ROOT / "linkedin scrape"),
            env={**os.environ, "HEADLESS": "true"},
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            return _json_error(err.splitlines()[-1] if err else "Scraper failed")
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


COMPANY_DIR = SECRETS / "web scraper" / "output" / "company"


@app.get("/api/reports")
def api_reports():
    reports = []
    if COMPANY_DIR.exists():
        for f in sorted(COMPANY_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                reports.append(data)
            except Exception:
                pass
    return jsonify({"ok": True, "reports": reports})


@app.get("/api/stats")
def api_stats():
    reports = []
    if COMPANY_DIR.exists():
        for f in COMPANY_DIR.glob("*.json"):
            try:
                reports.append(json.loads(f.read_text(encoding="utf-8")))
            except Exception:
                pass
    return jsonify({
        "ok": True,
        "total_companies": len(reports),
    })


FRONT_DIR = ROOT / "front"


@app.route("/front/")
@app.route("/front/<path:subpath>")
def serve_front(subpath="index.html"):
    from flask import send_from_directory
    fp = FRONT_DIR / subpath
    if fp.exists() and fp.is_file():
        return send_from_directory(str(FRONT_DIR), subpath)
    return send_from_directory(str(FRONT_DIR), "index.html")


@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


if __name__ == "__main__":
    app.run(debug=True, port=5000, threaded=True)
