import argparse
import json

from src.config import SUMMARY_JSON
from src.display import display_results
from src.scraper import run


def main() -> None:
    parser = argparse.ArgumentParser(description="LinkedIn profile scraper")
    parser.add_argument(
        "--view",
        action="store_true",
        help="Show saved results from output/ without scraping",
    )
    args = parser.parse_args()

    if args.view:
        display_results()
        return

    rows = run()
    summary = {}
    if SUMMARY_JSON.exists():
        summary = json.loads(SUMMARY_JSON.read_text(encoding="utf-8"))
    display_results(rows=rows, summary=summary)


if __name__ == "__main__":
    main()
