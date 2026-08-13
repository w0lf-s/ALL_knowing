from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SourceStatus(BaseModel):
    ok: bool = False
    error: str | None = None


class Resolved(BaseModel):
    ticker: str | None = None
    cik: str | None = None
    name: str | None = None
    website: str | None = None
    wiki_title: str | None = None
    domain: str | None = None
    exchanges: list[str] = Field(default_factory=list)
    sic: str | None = None
    sic_description: str | None = None


class Overview(BaseModel):
    legal_name: str | None = None
    description: str | None = None
    short_description: str | None = None
    industry: str | None = None
    sector: str | None = None
    headquarters: str | None = None
    country: str | None = None
    city: str | None = None
    state: str | None = None
    address: str | None = None
    founded: str | None = None
    ipo_date: str | None = None
    employees: int | str | None = None
    website: str | None = None
    phone: str | None = None
    logo_url: str | None = None
    thumbnail_url: str | None = None
    wikipedia_url: str | None = None
    currency: str | None = None
    share_class: str | None = None
    isin: str | None = None
    cusip: str | None = None
    figi: str | None = None
    via: list[str] = Field(default_factory=list)


class Financials(BaseModel):
    market_cap: int | float | str | None = None
    enterprise_value: float | None = None
    revenue: int | float | str | None = None
    gross_profit: float | None = None
    ebitda: float | None = None
    net_income: float | None = None
    eps: float | None = None
    diluted_eps_ttm: float | None = None
    book_value: float | None = None
    dividend_per_share: float | None = None
    dividend_yield: float | None = None
    dividend_date: str | None = None
    ex_dividend_date: str | None = None
    pe_ratio: float | None = None
    peg_ratio: float | None = None
    forward_pe: float | None = None
    price_to_sales_ttm: float | None = None
    price_to_book: float | None = None
    ev_to_revenue: float | None = None
    ev_to_ebitda: float | None = None
    profit_margin: float | None = None
    operating_margin_ttm: float | None = None
    return_on_assets_ttm: float | None = None
    return_on_equity_ttm: float | None = None
    revenue_ttm: float | None = None
    revenue_per_share_ttm: float | None = None
    quarterly_earnings_growth_yoy: float | None = None
    quarterly_revenue_growth_yoy: float | None = None
    analyst_target_price: float | None = None
    trailing_pe: float | None = None
    beta: float | None = None
    week_52_high: float | None = None
    week_52_low: float | None = None
    moving_average_50: float | None = None
    moving_average_200: float | None = None
    shares_outstanding: float | None = None
    shares_float: float | None = None
    percent_insiders: float | None = None
    percent_institutions: float | None = None
    metrics_raw: dict[str, Any] = Field(default_factory=dict)
    highlights: list[str] = Field(default_factory=list)
    via: list[str] = Field(default_factory=list)


class Filing(BaseModel):
    form: str | None = None
    filed_at: str | None = None
    accession_number: str | None = None
    title: str | None = None
    url: str | None = None
    via: list[str] = Field(default_factory=lambda: ["sec_edgar"])


class NewsArticle(BaseModel):
    title: str | None = None
    summary: str | None = None
    content: str | None = None
    url: str | None = None
    source_name: str | None = None
    published_at: str | None = None
    via: list[str] = Field(default_factory=list)


class News(BaseModel):
    digest_summary: str | None = None
    lookback_days: int = 3
    articles: list[NewsArticle] = Field(default_factory=list)


class PressItem(BaseModel):
    title: str | None = None
    summary: str | None = None
    url: str | None = None
    published_at: str | None = None
    feed_url: str | None = None
    via: list[str] = Field(default_factory=lambda: ["rss"])


class GithubOrg(BaseModel):
    login: str | None = None
    name: str | None = None
    html_url: str | None = None
    description: str | None = None
    blog: str | None = None
    location: str | None = None
    public_repos: int | None = None
    followers: int | None = None


class GithubRepo(BaseModel):
    name: str | None = None
    full_name: str | None = None
    url: str | None = None
    description: str | None = None
    stars: int | None = None
    language: str | None = None
    via: list[str] = Field(default_factory=lambda: ["github"])


class Github(BaseModel):
    org: GithubOrg = Field(default_factory=GithubOrg)
    repos: list[GithubRepo] = Field(default_factory=list)


class SourcesStatus(BaseModel):
    finnhub: SourceStatus = Field(default_factory=SourceStatus)
    alpha_vantage: SourceStatus = Field(default_factory=SourceStatus)
    yahoo: SourceStatus = Field(default_factory=SourceStatus)
    sec_edgar: SourceStatus = Field(default_factory=SourceStatus)
    nse: SourceStatus = Field(default_factory=SourceStatus)
    wikipedia: SourceStatus = Field(default_factory=SourceStatus)
    github: SourceStatus = Field(default_factory=SourceStatus)
    rss: SourceStatus = Field(default_factory=SourceStatus)
    newsapi: SourceStatus = Field(default_factory=SourceStatus)
    gnews: SourceStatus = Field(default_factory=SourceStatus)


class Meta(BaseModel):
    generated_at: str
    raw_path: str | None = None
    company_path: str | None = None


class CompanyDossier(BaseModel):
    query: str
    resolved: Resolved = Field(default_factory=Resolved)
    overview: Overview = Field(default_factory=Overview)
    financials: Financials = Field(default_factory=Financials)
    filings: list[Filing] = Field(default_factory=list)
    news: News = Field(default_factory=News)
    press: list[PressItem] = Field(default_factory=list)
    github: Github = Field(default_factory=Github)
    sources_status: SourcesStatus = Field(default_factory=SourcesStatus)
    meta: Meta
