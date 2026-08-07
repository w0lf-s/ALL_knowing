from __future__ import annotations

import re
from typing import Any

from rapidfuzz import fuzz

from src.adapters import CompanyContext, SourceResult
from src.adapters.alpha_vantage import map_overview_financials
from src.adapters.finnhub import domain_from_web
from src.cache import normalize_url
from src.news_enrich import sanitize_article_fields
from src.schema import (
    CompanyDossier,
    Filing,
    Financials,
    Github,
    GithubOrg,
    GithubRepo,
    Meta,
    News,
    NewsArticle,
    Overview,
    PressItem,
    Resolved,
    SourceStatus,
    SourcesStatus,
)


def _first(*vals: Any) -> Any:
    for v in vals:
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        return v
    return None


def _num(v: Any) -> float | None:
    if v is None or v == "None" or v == "-":
        return None
    try:
        return float(str(v).replace(",", ""))
    except Exception:
        return None


def _add_via(via: list[str], name: str) -> None:
    if name not in via:
        via.append(name)


def merge_dossier(
    query: str,
    ctx: CompanyContext,
    sources: dict[str, SourceResult],
    *,
    news_articles: list[dict[str, Any]] | None = None,
    lookback_days: int = 3,
    generated_at: str,
    raw_path: str | None = None,
    company_path: str | None = None,
) -> CompanyDossier:
    status = SourcesStatus()
    for name in (
        "finnhub",
        "alpha_vantage",
        "sec_edgar",
        "wikipedia",
        "github",
        "rss",
        "newsapi",
        "gnews",
    ):
        sr = sources.get(name)
        if sr is None:
            setattr(status, name, SourceStatus(ok=False, error="not_run"))
        else:
            setattr(status, name, SourceStatus(ok=sr.ok, error=sr.error))

    fh = sources.get("finnhub")
    av = sources.get("alpha_vantage")
    sec = sources.get("sec_edgar")
    wiki = sources.get("wikipedia")
    gh = sources.get("github")
    rss = sources.get("rss")

    profile: dict[str, Any] = {}
    metrics: dict[str, Any] = {}
    if fh and fh.ok and isinstance(fh.data, dict):
        profile = fh.data.get("profile") or {}
        metrics = (fh.data.get("metrics") or {}).get("metric") or fh.data.get("metrics") or {}

    av_data: dict[str, Any] = {}
    if av and av.ok and isinstance(av.data, dict):
        av_data = av.data

    wiki_summary: dict[str, Any] = {}
    if wiki and wiki.ok and isinstance(wiki.data, dict):
        wiki_summary = wiki.data.get("summary") or {}
        if not ctx.wiki_title:
            ctx.wiki_title = wiki.data.get("title")

    website = _first(profile.get("weburl"), av_data.get("Website"), ctx.website)
    domain = ctx.domain or domain_from_web(website)
    if not domain:
        domain = domain_from_web(profile.get("weburl"))

    resolved = Resolved(
        ticker=_first(ctx.ticker, av_data.get("Symbol")),
        cik=ctx.cik,
        name=_first(ctx.name, profile.get("name"), av_data.get("Name"), wiki_summary.get("title")),
        website=website,
        wiki_title=ctx.wiki_title,
        domain=domain,
        exchanges=[x for x in [profile.get("exchange"), av_data.get("Exchange")] if x],
        sic=ctx.sic,
        sic_description=ctx.sic_description,
    )
    if sec and sec.ok and isinstance(sec.data, dict):
        if not resolved.cik:
            resolved.cik = str(sec.data.get("cik", "")).zfill(10) or None
        if not resolved.name:
            resolved.name = sec.data.get("name")
        sic = None
        try:
            sic_list = (sec.data.get("sic") or None)
            if sic_list:
                sic = str(sic_list)
        except Exception:
            pass
        if isinstance(sec.data.get("sic"), (str, int)):
            resolved.sic = str(sec.data.get("sic"))
        resolved.sic_description = sec.data.get("sicDescription") or resolved.sic_description

    overview_via: list[str] = []
    overview = Overview(
        legal_name=_first(profile.get("name"), av_data.get("Name"), resolved.name),
        description=_first(wiki_summary.get("extract"), av_data.get("Description")),
        short_description=_first(wiki_summary.get("description"), (av_data.get("Description") or "")[:280] or None),
        industry=_first(profile.get("finnhubIndustry"), av_data.get("Industry")),
        sector=_first(av_data.get("Sector")),
        headquarters=_first(
            av_data.get("Address"),
            ", ".join([x for x in [profile.get("city"), profile.get("state"), profile.get("country")] if x]) or None,
        ),
        country=_first(profile.get("country"), av_data.get("Country")),
        city=profile.get("city"),
        state=profile.get("state"),
        address=av_data.get("Address"),
        founded=None,
        ipo_date=_first(profile.get("ipo"), av_data.get("IPODate")),
        employees=_first(profile.get("employeeTotal"), av_data.get("FullTimeEmployees")),
        website=website,
        phone=_first(profile.get("phone"), av_data.get("Phone")),
        logo_url=profile.get("logo"),
        thumbnail_url=wiki_summary.get("thumbnail", {}).get("source") if isinstance(wiki_summary.get("thumbnail"), dict) else None,
        wikipedia_url=(wiki_summary.get("content_urls") or {}).get("desktop", {}).get("page") if isinstance(wiki_summary.get("content_urls"), dict) else None,
        currency=_first(profile.get("currency"), av_data.get("Currency")),
        share_class=None,
        isin=av_data.get("ISIN"),
        cusip=None,
        figi=None,
        via=overview_via,
    )
    if profile:
        _add_via(overview_via, "finnhub")
    if av_data:
        _add_via(overview_via, "alpha_vantage")
    if wiki_summary:
        _add_via(overview_via, "wikipedia")
    if sec and sec.ok:
        _add_via(overview_via, "sec_edgar")

    fin_via: list[str] = []
    fin = Financials(highlights=[], metrics_raw={}, via=fin_via)
    if av_data:
        mapped = map_overview_financials(av_data)
        for k, v in mapped.items():
            if hasattr(fin, k) and getattr(fin, k) is None and v is not None:
                if k in ("dividend_date", "ex_dividend_date", "market_cap", "revenue"):
                    setattr(fin, k, v)
                else:
                    setattr(fin, k, _num(v))
        fin.metrics_raw = {k: av_data.get(k) for k in list(av_data.keys())[:40]}
        _add_via(fin_via, "alpha_vantage")
    if isinstance(metrics, dict) and metrics:
        mapping = {
            "marketCapitalization": "market_cap",
            "enterpriseValue": "enterprise_value",
            "52WeekHigh": "week_52_high",
            "52WeekLow": "week_52_low",
            "beta": "beta",
            "epsAnnual": "eps",
            "peBasicExclExtraTTM": "pe_ratio",
            "pbAnnual": "price_to_book",
            "psTTM": "price_to_sales_ttm",
            "roeTTM": "return_on_equity_ttm",
            "roaTTM": "return_on_assets_ttm",
            "grossMarginTTM": "profit_margin",
            "operatingMarginTTM": "operating_margin_ttm",
            "dividendYieldIndicatedAnnual": "dividend_yield",
        }
        for src_k, dst_k in mapping.items():
            if src_k == "enterpriseValue":
                continue
            if getattr(fin, dst_k) is None and metrics.get(src_k) is not None:
                setattr(fin, dst_k, _num(metrics.get(src_k)))
        fin.metrics_raw = {**(fin.metrics_raw or {}), **{k: metrics[k] for k in list(metrics.keys())[:40]}}
        _add_via(fin_via, "finnhub")

    filings: list[Filing] = []
    if sec and sec.ok and isinstance(sec.data, dict):
        recent = sec.data.get("filings", {}).get("recent") or {}
        forms = recent.get("form") or []
        dates = recent.get("filingDate") or []
        accessions = recent.get("accessionNumber") or []
        primary = recent.get("primaryDocument") or []
        descriptions = recent.get("primaryDocDescription") or []
        priority_rank = {
            "10-K": 0,
            "10-K/A": 1,
            "10-Q": 2,
            "10-Q/A": 3,
            "8-K": 4,
            "8-K/A": 5,
            "20-F": 6,
            "6-K": 7,
            "DEF 14A": 8,
            "DEFA14A": 9,
            "S-1": 10,
            "S-1/A": 11,
            "S-3": 12,
            "424B2": 13,
            "SD": 14,
        }
        insider_forms = {"3", "4", "5", "144"}
        parsed: list[Filing] = []
        seen: set[str] = set()
        for i in range(min(len(forms), 80)):
            acc = accessions[i] if i < len(accessions) else None
            if acc and acc in seen:
                continue
            if acc:
                seen.add(acc)
            form = forms[i]
            acc_nodash = (acc or "").replace("-", "")
            doc = primary[i] if i < len(primary) else ""
            desc = descriptions[i] if i < len(descriptions) else None
            cik = (resolved.cik or "").lstrip("0") or resolved.cik
            url = None
            if acc_nodash and cik and doc:
                url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{doc}"
            title = None
            if desc and str(desc).strip() and str(desc).strip().upper() != str(form).strip().upper():
                title = str(desc).strip()
            parsed.append(
                Filing(
                    form=form,
                    filed_at=dates[i] if i < len(dates) else None,
                    accession_number=acc,
                    title=title,
                    url=url,
                    via=["sec_edgar"],
                )
            )

        def _filed_key(f: Filing) -> str:
            return f.filed_at or ""

        major = [f for f in parsed if (f.form or "").upper() in priority_rank]
        other = [
            f
            for f in parsed
            if (f.form or "").upper() not in priority_rank and (f.form or "").upper() not in insider_forms
        ]
        insider = [f for f in parsed if (f.form or "").upper() in insider_forms]
        major.sort(key=_filed_key, reverse=True)
        other.sort(key=_filed_key, reverse=True)
        insider.sort(key=_filed_key, reverse=True)
        filings = (major[:12] + other[:5] + insider[:3])[:20]

    press: list[PressItem] = []
    if rss and rss.ok and isinstance(rss.data, dict):
        seen_u: set[str] = set()
        for item in rss.data.get("items") or []:
            u = normalize_url(item.get("url"))
            if u and u in seen_u:
                continue
            if u:
                seen_u.add(u)
            press.append(
                PressItem(
                    title=item.get("title"),
                    summary=item.get("summary"),
                    url=u,
                    published_at=item.get("published_at"),
                    feed_url=item.get("feed_url"),
                    via=["rss"],
                )
            )
            if len(press) >= 20:
                break

    github = Github()
    if gh and gh.ok and isinstance(gh.data, dict):
        org = gh.data.get("org") or {}
        github.org = GithubOrg(
            login=org.get("login"),
            name=org.get("name"),
            html_url=org.get("html_url"),
            description=org.get("description"),
            blog=org.get("blog"),
            location=org.get("location"),
            public_repos=org.get("public_repos"),
            followers=org.get("followers"),
        )
        repos = []
        for r in gh.data.get("repos") or []:
            repos.append(
                GithubRepo(
                    name=r.get("name"),
                    full_name=r.get("full_name"),
                    url=r.get("html_url"),
                    description=r.get("description"),
                    stars=r.get("stargazers_count"),
                    language=r.get("language"),
                    via=["github"],
                )
            )
        repos.sort(key=lambda x: x.stars or 0, reverse=True)
        github.repos = repos[:10]

    articles: list[NewsArticle] = []
    for a in news_articles or []:
        cleaned = sanitize_article_fields(a)
        articles.append(NewsArticle(**{k: cleaned.get(k) for k in NewsArticle.model_fields.keys()}))

    if not resolved.domain and domain:
        resolved.domain = domain
    ctx.website = resolved.website
    ctx.domain = resolved.domain

    return CompanyDossier(
        query=query,
        resolved=resolved,
        overview=overview,
        financials=fin,
        filings=filings,
        news=News(digest_summary=None, lookback_days=lookback_days, articles=articles),
        press=press,
        github=github,
        sources_status=status,
        meta=Meta(generated_at=generated_at, raw_path=raw_path, company_path=company_path),
    )


def is_english_text(text: str | None) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    if re.search(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af\u0400-\u04ff\u0600-\u06ff]", raw):
        return False
    sample = raw[:1000]
    try:
        from langdetect import DetectorFactory, detect

        DetectorFactory.seed = 0
        return detect(sample) == "en"
    except Exception:
        letters = sum(1 for ch in sample if ch.isalpha())
        ascii_letters = sum(1 for ch in sample if "a" <= ch.lower() <= "z")
        if letters == 0:
            return False
        return (ascii_letters / letters) >= 0.85


def is_english_article(article: dict[str, Any]) -> bool:
    title = (article.get("title") or "").strip()
    if not title:
        return False
    low = title.lower()
    if low in ("[removed]", "null", "untitled", "(untitled)"):
        return False
    if re.fullmatch(r"[\w.-]+\.[a-z]{2,}(/)?", title, flags=re.I):
        return False
    parts = [article.get("title"), article.get("summary"), article.get("content")]
    text = " ".join(str(p) for p in parts if p)
    return is_english_text(text)


def merge_news_articles(
    batches: list[list[dict[str, Any]]],
    limit: int = 8,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    by_url: dict[str, dict[str, Any]] = {}
    for batch in batches:
        for a in batch:
            url = normalize_url(a.get("url"))
            if not url:
                continue
            if url in by_url:
                existing = by_url[url]
                vias = list(dict.fromkeys((existing.get("via") or []) + (a.get("via") or [])))
                existing["via"] = vias
                if not existing.get("summary") and a.get("summary"):
                    existing["summary"] = a.get("summary")
                continue
            item = dict(a)
            item["url"] = url
            item = sanitize_article_fields(item)
            by_url[url] = item
            merged.append(item)

    deduped: list[dict[str, Any]] = []
    for a in merged:
        title = (a.get("title") or "").strip()
        if not title:
            continue
        if not is_english_article(a):
            continue
        dup = False
        for b in deduped:
            if fuzz.token_set_ratio(title, (b.get("title") or "")) >= 92:
                vias = list(dict.fromkeys((b.get("via") or []) + (a.get("via") or [])))
                b["via"] = vias
                dup = True
                break
        if not dup:
            deduped.append(a)

    def sort_key(x: dict[str, Any]) -> str:
        return x.get("published_at") or ""

    deduped.sort(key=sort_key, reverse=True)
    return deduped[:limit]
