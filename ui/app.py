import asyncio
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECRETS = ROOT / "not to share"
VENV_PYTHON = SECRETS / ".venv" / "Scripts" / "python.exe"

from dotenv import load_dotenv

load_dotenv(SECRETS / ".env")

from flask import Flask, render_template, request

app = Flask(__name__)

WS_SRC = ROOT / "web scraper" / "src"

sys.path.insert(0, str(ROOT / "web scraper"))


@app.route("/")
def index():
    return render_template("company.html")


@app.route("/company", methods=["GET", "POST"])
def company():
    dossier = None
    error = None
    query = ""
    if request.method == "POST":
        query = (request.form.get("query") or "").strip()
        if query:
            try:
                from src.pipeline import run_pipeline

                dossier = asyncio.run(
                    run_pipeline(query, use_groq=True, use_playwright=True)
                )
                dossier = dossier.model_dump()
            except Exception as exc:
                error = str(exc)
    return render_template("company.html", dossier=dossier, error=error, query=query)


_LI_RUNNER = '''
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
'''


@app.route("/linkedin", methods=["GET", "POST"])
def linkedin():
    profile = None
    error = None
    url = ""
    if request.method == "POST":
        url = (request.form.get("url") or "").strip()
        if url:
            try:
                script = _LI_RUNNER.format(li_root=str(ROOT / "linkedin scrape").replace("\\", "\\\\"))
                import os
                env = {**os.environ, "HEADLESS": "true"}
                result = subprocess.run(
                    [str(VENV_PYTHON), "-c", script, url],
                    capture_output=True,
                    text=True,
                    timeout=120,
                    cwd=str(ROOT / "linkedin scrape"),
                    env=env,
                )
                if result.returncode != 0:
                    error = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "Scraper failed"
                else:
                    output = result.stdout.strip()
                    if output:
                        profile = json.loads(output)
            except subprocess.TimeoutExpired:
                error = "LinkedIn scraper timed out (120s)"
            except Exception as exc:
                error = str(exc)
    return render_template("linkedin.html", profile=profile, error=error, url=url)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
