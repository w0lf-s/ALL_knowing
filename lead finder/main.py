from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.cookie_parse import primary_email_from_cookie_file
from src.display import display_report
from src.email_parse import classify_email
from src.orchestrate import run_lead_finder

SAMPLE_COOKIE = ROOT / "sample" / "cookie-sample.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Lead finder CLI")
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
        "--parse-only",
        action="store_true",
        help="Only print parsed email fields and exit",
    )
    args = parser.parse_args()

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
            f"(sample: --cookie \"{SAMPLE_COOKIE}\")"
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

    result = run_lead_finder(
        email,
        max_profiles=max(1, args.max_profiles),
        no_company=args.no_company,
        no_scrape=args.no_scrape,
        headless=not args.headed,
    )
    display_report(result)


if __name__ == "__main__":
    main()
