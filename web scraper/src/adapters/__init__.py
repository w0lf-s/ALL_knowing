from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CompanyContext:
    query: str
    ticker: str | None = None
    cik: str | None = None
    name: str | None = None
    website: str | None = None
    domain: str | None = None
    wiki_title: str | None = None
    exchanges: list[str] = field(default_factory=list)
    sic: str | None = None
    sic_description: str | None = None


@dataclass
class SourceResult:
    source: str
    ok: bool
    data: Any = None
    error: str | None = None
