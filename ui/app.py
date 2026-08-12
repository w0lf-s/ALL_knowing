import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECRETS = ROOT / "not to share"
VENV_PYTHON = SECRETS / ".venv" / "Scripts" / "python.exe"
LEAD_FINDER_DIR = ROOT / "lead finder"
COOKIES_DIR = SECRETS / "lead finder" / "cookies"

from dotenv import load_dotenv

load_dotenv(SECRETS / ".env")

from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

sys.path.insert(0, str(ROOT / "web scraper"))


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/lead")
@app.route("/company")
@app.route("/linkedin")
def spa_alias():
    return render_template("index.html")


def _json_error(message: str, status: int = 400):
    return jsonify({"ok": False, "error": message}), status


def _last_json_line(stdout: str):
    lines = [ln for ln in (stdout or "").splitlines() if ln.strip()]
    if not lines:
        return None
    return json.loads(lines[-1])


_LI_RUNNER = """
import json, sys
sys.path.insert(0, r"{li_root}")
from src.config import URLS_PATH, get_settings, ensure_dirs
from src.scraper import run
ensure_dirs()
URLS_PATH.parent.mkdir(parents=True, exist_ok=True)
URLS_PATH.write_text(sys.argv[1] + "\\n", encoding="utf-8")
rows = run(get_settings())
if rows:
    print(json.dumps(rows[0], default=str))
else:
    print("{{}}")
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
        proc = subprocess.run(
            [
                str(VENV_PYTHON),
                "-c",
                script,
                email,
                "",
                str(max(1, min(max_profiles, 10))),
            ],
            capture_output=True,
            text=True,
            timeout=600,
            cwd=str(LEAD_FINDER_DIR),
            env={**os.environ, "HEADLESS": "true"},
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            return _json_error(
                err.splitlines()[-1] if err else "Lead investigation failed"
            )
        result = _last_json_line(proc.stdout)
        if not result:
            return _json_error("Lead investigation returned no output")
        return jsonify({"ok": True, "result": result})
    except subprocess.TimeoutExpired:
        return _json_error("Lead investigation timed out", 504)
    except Exception as exc:
        return _json_error(str(exc))


@app.post("/api/company")
def api_company():
    data = request.get_json(silent=True) or {}
    query = str(data.get("query") or "").strip()
    if not query:
        return _json_error("Enter a company name")
    try:
        from src.pipeline import run_pipeline

        dossier = asyncio.run(run_pipeline(query, use_groq=True, use_playwright=True))
        return jsonify({"ok": True, "dossier": dossier.model_dump()})
    except Exception as exc:
        return _json_error(str(exc))


@app.post("/api/linkedin")
def api_linkedin():
    data = request.get_json(silent=True) or {}
    url = str(data.get("url") or "").strip()
    if not url:
        return _json_error("Enter a LinkedIn profile URL")
    try:
        script = _LI_RUNNER.format(
            li_root=str(ROOT / "linkedin scrape").replace("\\", "\\\\")
        )
        proc = subprocess.run(
            [str(VENV_PYTHON), "-c", script, url],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(ROOT / "linkedin scrape"),
            env={**os.environ, "HEADLESS": "true"},
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            return _json_error(err.splitlines()[-1] if err else "Scraper failed")
        profile = _last_json_line(proc.stdout) or {}
        return jsonify({"ok": True, "profile": profile})
    except subprocess.TimeoutExpired:
        return _json_error("LinkedIn scraper timed out (120s)", 504)
    except Exception as exc:
        return _json_error(str(exc))


if __name__ == "__main__":
    app.run(debug=True, port=5000)
