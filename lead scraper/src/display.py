import json
from pathlib import Path
from typing import Any

from src.config import RESULTS_JSON, SUMMARY_JSON


def _value(raw: Any) -> str:
    if raw is None:
        return "-"
    if isinstance(raw, list):
        if not raw:
            return "-"
        parts: list[str] = []
        for item in raw:
            if isinstance(item, dict):
                if item.get("value"):
                    value = str(item.get("value") or "").replace("\n", " ").strip()
                    source = str(item.get("source") or "").replace("\n", " ").strip()
                    parts.append(f"{value} ({source})" if source else value)
                    continue
                title = str(item.get("title") or "").replace("\n", " ").strip()
                url = str(item.get("url") or "").replace("\n", " ").strip()
                if title and url and title != url:
                    parts.append(f"{title} ({url})")
                elif url:
                    parts.append(url)
                elif title:
                    parts.append(title)
            elif item:
                parts.append(str(item).replace("\n", " ").strip())
        return "; ".join(parts) if parts else "-"
    text = str(raw).replace("\n", " ").strip()
    return text if text else "-"


def _format_links(links: Any) -> list[str]:
    if not isinstance(links, list) or not links:
        return ["  Links    : -"]
    lines = [f"  Links    : {len(links)}"]
    for index, item in enumerate(links, start=1):
        if isinstance(item, dict):
            title = str(item.get("title") or "Link").replace("\n", " ").strip()
            url = str(item.get("url") or "").replace("\n", " ").strip()
            lines.append(f"    {index}. {title}")
            if url:
                lines.append(f"       {url}")
        else:
            lines.append(f"    {index}. {str(item).replace(chr(10), ' ').strip()}")
    return lines


def _row_lines(index: int, row: dict[str, Any]) -> list[str]:
    failed = bool(row.get("error")) or not row.get("name")
    status = "FAILED" if failed else "OK"
    fields = [
        ("#", str(index)),
        ("Status", status),
        ("Name", _value(row.get("name"))),
        ("Headline", _value(row.get("headline"))),
        ("Role", _value(row.get("current_role"))),
        ("Company", _value(row.get("current_company"))),
        ("Location", _value(row.get("location"))),
        ("Email", _value(row.get("email"))),
        ("Phone", _value(row.get("phone"))),
        ("Twitter", _value(row.get("twitter"))),
        ("Profile", _value(row.get("linkedin_profile_url") or row.get("url"))),
        ("About", _value(row.get("about"))),
        ("Error", _value(row.get("error"))),
    ]
    extra = [
        ("Emails", row.get("email_entries") or [x for x in (row.get("emails") or []) if x and x != row.get("email")]),
        ("Phones", row.get("phone_entries") or [x for x in (row.get("phones") or []) if x and x != row.get("phone")]),
        ("Company emails", row.get("company_email_entries") or row.get("company_emails")),
        ("Company phones", row.get("company_phone_entries") or row.get("company_phones")),
    ]
    for label, raw in extra:
        text = _value(raw)
        if text != "-":
            fields.insert(-3, (label, text))
    label_width = max(len(label) for label, _ in fields)
    lines = ["-" * 72, f" Profile {index} ".center(72, "-")]
    for label, value in fields:
        lines.append(f"  {label:<{label_width}} : {value}")
    lines.extend(_format_links(row.get("links")))
    return lines


def load_results(path: Path = RESULTS_JSON) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    return []


def load_summary(path: Path = SUMMARY_JSON) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def format_results(
    rows: list[dict[str, Any]] | None = None,
    summary: dict[str, Any] | None = None,
) -> str:
    rows = rows if rows is not None else load_results()
    summary = summary if summary is not None else load_summary()
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append(" Lead scraper results ".center(72, "="))
    lines.append("=" * 72)

    if summary:
        total = summary.get("total", len(rows))
        success = summary.get(
            "success",
            sum(1 for r in rows if not r.get("error") and r.get("name")),
        )
        failed = summary.get(
            "failed",
            sum(1 for r in rows if r.get("error") or not r.get("name")),
        )
        lines.append(f"  Total   : {total}")
        lines.append(f"  Success : {success}")
        lines.append(f"  Failed  : {failed}")
    else:
        lines.append(f"  Total   : {len(rows)}")

    if not rows:
        lines.append("-" * 72)
        lines.append("  No results found. Run: python main.py")
        lines.append("=" * 72)
        return "\n".join(lines)

    for index, row in enumerate(rows, start=1):
        lines.extend(_row_lines(index, row))

    lines.append("-" * 72)
    lines.append(f"  Files: {RESULTS_JSON}")
    lines.append("=" * 72)
    return "\n".join(lines)


def display_results(
    rows: list[dict[str, Any]] | None = None,
    summary: dict[str, Any] | None = None,
) -> None:
    print(format_results(rows=rows, summary=summary))
