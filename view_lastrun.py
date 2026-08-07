from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
DEFAULT = ROOT / "lastrun.json"
REQUIRED = (
    "query",
    "resolved",
    "overview",
    "financials",
    "filings",
    "news",
    "press",
    "github",
    "sources_status",
    "meta",
)


def load(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"Missing file: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit("lastrun.json must be an object")
    missing = [k for k in REQUIRED if k not in data]
    if missing:
        raise SystemExit(f"Missing keys: {', '.join(missing)}")
    return data


def clip_words(text: str, max_words: int = 300) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text.strip()
    return " ".join(words[:max_words]).strip() + " ..."


def skip_null(d: dict) -> dict:
    return {k: v for k, v in d.items() if v not in (None, "", [], {})}


def plain(value) -> str:
    return escape(str(value) if value is not None else "")


MONEY_KEYS = {
    "market_cap",
    "enterprise_value",
    "revenue",
    "gross_profit",
    "ebitda",
    "net_income",
    "eps",
    "diluted_eps_ttm",
    "book_value",
    "dividend_per_share",
    "analyst_target_price",
    "week_52_high",
    "week_52_low",
    "moving_average_50",
    "moving_average_200",
    "revenue_ttm",
    "revenue_per_share_ttm",
}

PERCENT_KEYS = {
    "dividend_yield",
    "profit_margin",
    "operating_margin_ttm",
    "return_on_assets_ttm",
    "return_on_equity_ttm",
    "quarterly_earnings_growth_yoy",
    "quarterly_revenue_growth_yoy",
    "percent_insiders",
    "percent_institutions",
}

CURRENCY_SYMBOLS = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "JPY": "¥",
    "CNY": "¥",
    "INR": "₹",
    "CAD": "C$",
    "AUD": "A$",
    "CHF": "CHF ",
    "HKD": "HK$",
}


def _to_float(value) -> float | None:
    try:
        return float(str(value).replace(",", "").strip())
    except Exception:
        return None


def format_money(value, currency: str | None) -> str:
    num = _to_float(value)
    if num is None:
        return str(value)
    code = (currency or "USD").upper()
    symbol = CURRENCY_SYMBOLS.get(code, f"{code} ")
    abs_num = abs(num)
    sign = "-" if num < 0 else ""
    if abs_num >= 1_000_000_000_000:
        compact = f"{abs_num / 1_000_000_000_000:.2f}T"
    elif abs_num >= 1_000_000_000:
        compact = f"{abs_num / 1_000_000_000:.2f}B"
    elif abs_num >= 1_000_000:
        compact = f"{abs_num / 1_000_000:.2f}M"
    elif abs_num >= 1_000:
        compact = f"{abs_num:,.2f}"
    else:
        compact = f"{abs_num:.4g}"
    return f"{sign}{symbol}{compact} {code}".strip()


def format_financial_value(key: str, value, currency: str | None) -> str:
    if key in MONEY_KEYS:
        return format_money(value, currency)
    if key in PERCENT_KEYS:
        num = _to_float(value)
        if num is None:
            return str(value)
        pct = num * 100 if abs(num) <= 1 else num
        return f"{pct:.2f}%"
    num = _to_float(value)
    if num is not None and abs(num) >= 1000 and key in {"shares_outstanding", "shares_float"}:
        return f"{num:,.0f}"
    return str(value)


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean view of lastrun.json")
    parser.add_argument("--path", type=Path, default=DEFAULT)
    args = parser.parse_args()
    data = load(args.path)
    console = Console(force_terminal=True, legacy_windows=False)

    resolved = data.get("resolved") or {}
    meta = data.get("meta") or {}
    header = Text()
    header.append(str(data.get("query") or ""), style="bold")
    bits = [
        resolved.get("name"),
        resolved.get("ticker"),
        resolved.get("cik"),
        meta.get("generated_at"),
    ]
    sub = " · ".join(str(b) for b in bits if b)
    company = Text()
    company.append_text(header)
    if sub:
        company.append("\n")
        company.append(sub)
    console.print(Panel(company, title="Company"))

    overview = skip_null(data.get("overview") or {})
    if overview:
        t = Table(show_header=False, box=None, padding=(0, 2))
        t.add_column("k", style="dim")
        t.add_column("v", overflow="fold")
        for k in (
            "legal_name",
            "industry",
            "sector",
            "headquarters",
            "employees",
            "website",
            "currency",
            "short_description",
            "description",
        ):
            if k in overview and overview[k] is not None:
                t.add_row(k, plain(overview[k]))
        console.print(Panel(t, title="Overview"))

    financials = data.get("financials") or {}
    currency = (data.get("overview") or {}).get("currency") or "USD"
    ft = Table(title=None, show_header=True)
    ft.add_column("Metric")
    ft.add_column("Value", justify="right", overflow="fold")
    shown = 0
    for k, v in financials.items():
        if k in ("metrics_raw", "highlights", "via"):
            continue
        if v is None or v == "":
            continue
        ft.add_row(plain(k), plain(format_financial_value(k, v, currency)))
        shown += 1
        if shown >= 24:
            break
    if shown:
        console.print(Panel(ft, title=f"Financials ({currency})"))
    highlights = financials.get("highlights") or []
    if highlights:
        console.print(
            Panel(Text("\n".join(f"• {h}" for h in highlights)), title="Highlights")
        )

    filings = data.get("filings") or []
    if filings:
        lines = []
        for f in filings[:12]:
            form = f.get("form") or "?"
            filed = f.get("filed_at") or ""
            title = f.get("title")
            url = f.get("url")
            line = f"{form}  {filed}".rstrip()
            if title and str(title).strip().upper() != str(form).strip().upper():
                line += f"\n  {title}"
            if url:
                line += f"\n  {url}"
            lines.append(line)
        more = len(filings) - 12
        if more > 0:
            lines.append(f"+{more} more")
        console.print(Panel(Text("\n".join(lines)), title="Filings"))

    news = data.get("news") or {}
    digest = news.get("digest_summary")
    articles = news.get("articles") or []
    body = []
    if digest:
        body.append(str(digest))
        body.append("")
    for a in articles[:8]:
        line = f"• {a.get('title') or '(untitled)'}"
        meta_bits = [a.get("source_name"), a.get("published_at")]
        meta_s = " · ".join(str(x) for x in meta_bits if x)
        if meta_s:
            line += f"\n  {meta_s}"
        if a.get("url"):
            line += f"\n  {a.get('url')}"
        content = a.get("content")
        if content:
            line += f"\n  {clip_words(str(content), 300)}"
        body.append(line)
    if body:
        console.print(Panel(Text("\n".join(body)), title="News"))

    press = data.get("press") or []
    if press:
        lines = []
        for p in press[:10]:
            lines.append(f"• {p.get('title') or ''}  {p.get('published_at') or ''}\n  {p.get('url') or ''}")
        more = len(press) - 10
        if more > 0:
            lines.append(f"+{more} more")
        console.print(Panel(Text("\n".join(lines)), title="Press"))

    github = data.get("github") or {}
    org = github.get("org") or {}
    repos = github.get("repos") or []
    g_lines = []
    if any(org.get(k) for k in ("login", "name", "html_url")):
        g_lines.append(
            f"{org.get('name') or org.get('login') or ''}  {org.get('html_url') or ''}"
        )
        if org.get("description"):
            g_lines.append(str(org.get("description")))
    for r in repos[:5]:
        g_lines.append(
            f"• {r.get('full_name') or r.get('name')}  stars:{r.get('stars') or 0}  {r.get('language') or ''}\n  {r.get('url') or ''}"
        )
    if g_lines:
        console.print(Panel(Text("\n".join(g_lines)), title="GitHub"))

    st = Table(show_header=True)
    st.add_column("Source")
    st.add_column("OK")
    st.add_column("Error", overflow="fold")
    for name, val in (data.get("sources_status") or {}).items():
        if not isinstance(val, dict):
            continue
        st.add_row(
            plain(name),
            "yes" if val.get("ok") else "no",
            plain(val.get("error") or ""),
        )
    console.print(Panel(st, title="Sources"))


if __name__ == "__main__":
    main()
