from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_PYTHON = ROOT.parent / "not to share" / ".venv" / "Scripts" / "python.exe"


def _ensure_venv() -> None:
    if not VENV_PYTHON.exists():
        return
    try:
        current = Path(sys.executable).resolve()
        target = VENV_PYTHON.resolve()
    except Exception:
        return
    if current == target:
        return
    cmd = [str(VENV_PYTHON), str(ROOT / "main.py"), *sys.argv[1:]]
    raise SystemExit(subprocess.call(cmd))


_ensure_venv()

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import COOKIES_DIR
from src.cookie_parse import load_sample_leads, primary_email_from_cookie_file
from src.display import display_report
from src.email_parse import classify_email
from src.orchestrate import run_lead_finder

SAMPLE_COOKIES = COOKIES_DIR


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Lead finder: email/cookie → company (web scraper) → "
            "LinkedIn people search → profile scrape"
        )
    )
    parser.add_argument(
        "email",
        nargs="?",
        default=None,
        help="Viewer email address, e.g. abc@google.com",
    )
    parser.add_argument(
        "--cookie",
        type=Path,
        default=None,
        help="Cookie snapshot JSON (CRM format). Uses embedded email if email arg omitted.",
    )
    parser.add_argument(
        "--max-profiles",
        type=int,
        default=5,
        help="Max LinkedIn /in/ URLs to collect and scrape",
    )
    parser.add_argument(
        "--no-company",
        action="store_true",
        help="Skip web scraper company lookup",
    )
    parser.add_argument(
        "--no-scrape",
        action="store_true",
        help="Only find candidate LinkedIn URLs; do not scrape profiles",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Show browser window (useful for LinkedIn login)",
    )
    parser.add_argument(
        "--list-samples",
        action="store_true",
        help="List sample cookie leads from not to share/lead finder/cookies/",
    )
    parser.add_argument(
        "--parse-only",
        action="store_true",
        help="Only print parsed email fields and exit (no scrapers)",
    )
    args = parser.parse_args()

    if args.list_samples:
        for lead in load_sample_leads():
            print(f"{lead['email']}  {lead.get('title') or ''}  {lead.get('linkedin_url') or ''}")
        return

    email = args.email
    if args.cookie is not None:
        cookie_path = args.cookie
        if not cookie_path.exists():
            raise SystemExit(f"Cookie file not found: {cookie_path}")
        if not email:
            email = primary_email_from_cookie_file(cookie_path)
    if not email:
        raise SystemExit(
            "Provide an email or --cookie path "
            f"(samples: {SAMPLE_COOKIES})"
        )

    if args.parse_only:
        parsed = classify_email(email)
        display_report(
            {
                "parsed": parsed.to_dict(),
                "candidate_urls": [],
                "profiles": [],
                "skip_search": True,
            }
        )
        return

    run_lead_finder(
        email,
        max_profiles=max(1, args.max_profiles),
        no_company=args.no_company,
        no_scrape=args.no_scrape,
        headless=not args.headed,
        live=True,
    )


if __name__ == "__main__":
    main()
