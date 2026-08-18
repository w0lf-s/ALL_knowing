from __future__ import annotations

import os
import re
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import unquote, urljoin, urlparse

import httpx

LEAD_ROOT = Path(__file__).resolve().parent.parent
WEB_ROOT = LEAD_ROOT.parent / "web scraper"
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
JUNK = (
    "noreply",
    "no-reply",
    "privacy",
    "sentry.io",
    "wixpress",
    "example.com",
    "placeholder",
    "yourdomain",
    "email.com",
    "domain.com",
)
SKIP_HOST = (
    "linkedin.com",
    "lnkd.in",
    "facebook.com",
    "instagram.com",
    "youtube.com",
    "github.com",
)
PATHS = (
    "/",
    "/contact",
    "/contact-us",
    "/about",
    "/about-us",
    "/team",
    "/leadership",
    "/investors",
    "/press",
)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ZuntraLeadIntel/1.0)",
    "Accept": "text/html,application/json",
}
GENERIC = (
    "info@",
    "hello@",
    "support@",
    "press@",
    "media@",
    "ir@",
    "contact@",
    "sales@",
    "admin@",
    "webmaster@",
)
CO_NAME_SKIP = (
    "technologies",
    "technology",
    "solutions",
    "limited",
    "private",
    "company",
    "group",
    "international",
    "services",
    "corp",
    "inc",
    "llc",
    "ltd",
    "the",
    "and",
)
_robots: dict[str, list[str]] = {}


@contextmanager
def _web_src() -> Iterator[None]:
    lead = str(LEAD_ROOT)
    web = str(WEB_ROOT)
    removed: list[tuple[int, str]] = []
    for i, entry in list(enumerate(sys.path)):
        if entry == lead or entry.rstrip("\\/") == lead.rstrip("\\/"):
            removed.append((i, entry))
    for i, _ in reversed(removed):
        sys.path.pop(i)
    if web in sys.path:
        sys.path.remove(web)
    sys.path.insert(0, web)
    cached = {k: sys.modules.pop(k) for k in list(sys.modules) if k == "src" or k.startswith("src.")}
    try:
        yield
    finally:
        for k in list(sys.modules):
            if k == "src" or k.startswith("src."):
                sys.modules.pop(k, None)
        sys.modules.update(cached)
        if web in sys.path:
            sys.path.remove(web)
        for i, entry in removed:
            sys.path.insert(min(i, len(sys.path)), entry)


def _as_list(val: Any) -> list:
    return list(val) if isinstance(val, list) else []


def _clean_email(raw: str) -> str | None:
    text = str(raw or "").strip().lower().rstrip(".,;:)>\\/")
    if text.endswith("\\"):
        text = text[:-1].strip()
    if not text or "@" not in text:
        return None
    if any(j in text for j in JUNK):
        return None
    if text.endswith((".png", ".jpg", ".gif", ".svg", ".webp")):
        return None
    local, _, host = text.partition("@")
    if not local or not host or "." not in host or " " in text:
        return None
    return text


def _clean_phone(raw: str) -> str | None:
    original = str(raw or "").strip().rstrip("\\")
    if original.count(".") > 1:
        return None
    if re.search(r"[A-Za-z]", original):
        return None
    digits = re.sub(r"\D", "", original)
    if len(digits) < 10 or len(digits) > 15:
        return None
    groups = [g for g in re.split(r"\D+", original) if g]
    if sum(1 for g in groups if len(g) == 1) > 2:
        return None
    if original.startswith("+"):
        return "+" + digits
    if len(digits) == 12 and digits.startswith("91"):
        return "+" + digits
    if len(digits) == 11 and digits.startswith("0"):
        return digits
    return digits


def _phone_key(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _email_matches_name(email: str, name: str) -> bool:
    local = (email or "").split("@", 1)[0].lower()
    parts = re.findall(r"[a-z]+", (name or "").lower())
    if not local or not parts:
        return False
    first, last = parts[0], parts[-1]
    compact = re.sub(r"[^a-z]", "", local)
    return any(
        token and token in compact
        for token in (
            first,
            last,
            first + last,
            last + first,
            (first[0] + last) if first else "",
        )
    )


def _add_email(entries: list[dict[str, str]], raw: str, source: str) -> None:
    cleaned = _clean_email(raw)
    if not cleaned:
        return
    if any(item["value"] == cleaned for item in entries):
        return
    entries.append({"value": cleaned, "source": source})


def _add_phone(entries: list[dict[str, str]], raw: str, source: str) -> None:
    cleaned = _clean_phone(raw)
    if not cleaned:
        return
    key = _phone_key(cleaned)
    if any(_phone_key(item["value"]) == key for item in entries):
        return
    entries.append({"value": cleaned, "source": source})


def _origin(url: str) -> str | None:
    try:
        parsed = urlparse(url)
        if parsed.scheme in ("http", "https") and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    except Exception:
        return None
    return None


def _is_generic_email(email: str) -> bool:
    return any((email or "").startswith(g) for g in GENERIC)


def _company_tokens(company: str) -> list[str]:
    return [
        t
        for t in re.findall(r"[a-z0-9]+", (company or "").lower())
        if len(t) > 3 and t not in CO_NAME_SKIP
    ]


def _host_matches_company(url: str, company: str) -> bool:
    host = (urlparse(url).netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    tokens = _company_tokens(company)
    return bool(host and tokens and any(t in host for t in tokens))


def _emails_in_text(html: str) -> list[str]:
    emails = []
    for raw in EMAIL_RE.findall(html or ""):
        cleaned = _clean_email(raw)
        if cleaned and cleaned not in emails:
            emails.append(cleaned)
    return emails


def _extract_from_html(html: str) -> tuple[list[str], list[str]]:
    emails = []
    phones = []
    for href in re.findall(r"mailto:([^\"'\s>]+)", html or "", re.I):
        cleaned = _clean_email(unquote(href.split("?")[0]))
        if cleaned and cleaned not in emails:
            emails.append(cleaned)
    for href in re.findall(r"tel:([^\"'\s>]+)", html or "", re.I):
        cleaned = _clean_phone(unquote(href))
        if cleaned and cleaned not in phones:
            phones.append(cleaned)
    return emails, phones


def _blocked(client: httpx.Client, url: str) -> bool:
    origin = _origin(url)
    if not origin:
        return True
    if origin not in _robots:
        text = _fetch(client, origin + "/robots.txt", check_robots=False)
        denies: list[str] = []
        apply = False
        for line in (text or "").splitlines():
            low = line.strip().lower()
            if low.startswith("user-agent:"):
                apply = "*" in low.split(":", 1)[-1]
            elif apply and low.startswith("disallow:"):
                path = line.split(":", 1)[-1].strip()
                if path:
                    denies.append(path)
        _robots[origin] = denies
    path = urlparse(url).path or "/"
    for deny in _robots[origin]:
        if deny == "/":
            return True
        if path.startswith(deny):
            return True
    return False


def _fetch(client: httpx.Client, url: str, *, check_robots: bool = True) -> str:
    if check_robots and _blocked(client, url):
        return ""
    try:
        resp = client.get(url, headers=HEADERS, follow_redirects=True, timeout=8.0)
        if resp.status_code >= 400:
            return ""
        ctype = (resp.headers.get("content-type") or "").lower()
        if "html" not in ctype and "text" not in ctype and "json" not in ctype:
            return ""
        return resp.text[:400000]
    except Exception:
        return ""


def _scan_site(client: httpx.Client, base: str) -> tuple[list[str], list[str]]:
    origin = _origin(base)
    if not origin:
        return [], []
    emails: list[str] = []
    phones: list[str] = []
    seen = set()
    for path in PATHS:
        url = urljoin(origin + "/", path.lstrip("/"))
        if url in seen:
            continue
        seen.add(url)
        html = _fetch(client, url)
        found_e, found_p = _extract_from_html(html)
        for item in _emails_in_text(html):
            if item not in found_e:
                found_e.append(item)
        for item in found_e:
            if item not in emails:
                emails.append(item)
        for item in found_p:
            if item not in phones:
                phones.append(item)
        time.sleep(0.35)
    return emails, phones


def _iter_urls(row: dict[str, Any]) -> list[str]:
    out = []
    for item in row.get("links") or []:
        if isinstance(item, dict):
            url = str(item.get("url") or "").strip()
        else:
            url = str(item or "").strip()
        if url and url not in out:
            out.append(url)
    extra = row.get("twitter")
    if extra:
        url = str(extra)
        if url.startswith("http") and url not in out:
            out.append(url)
    return out


def _link_urls(row: dict[str, Any]) -> list[str]:
    out = []
    for url in _iter_urls(row):
        host = (urlparse(url).netloc or "").lower()
        if any(s in host for s in SKIP_HOST):
            continue
        if url not in out:
            out.append(url)
    return out[:5]


def _github_login(url: str) -> str | None:
    try:
        parsed = urlparse(url)
    except Exception:
        return None
    host = (parsed.netloc or "").lower()
    if host not in ("github.com", "www.github.com"):
        return None
    parts = [p for p in (parsed.path or "").strip("/").split("/") if p]
    if not parts:
        return None
    skip = {
        "login",
        "orgs",
        "features",
        "topics",
        "settings",
        "marketplace",
        "about",
        "pricing",
        "explore",
        "notifications",
        "issues",
        "pulls",
        "codespaces",
        "sponsors",
    }
    if parts[0].lower() in skip:
        return None
    return parts[0]


def _github_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "zuntra-lead-intel",
    }
    token = (os.getenv("GITHUB_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _github_json(client: httpx.Client, url: str, params: dict[str, Any] | None = None) -> Any:
    try:
        resp = client.get(url, params=params, headers=_github_headers(), timeout=8.0)
        if resp.status_code >= 400:
            return None
        return resp.json()
    except Exception:
        return None


def _github_for_login(client: httpx.Client, login: str) -> str | None:
    data = _github_json(client, f"https://api.github.com/users/{login}")
    if not isinstance(data, dict):
        return None
    return _clean_email(data.get("email") or "")


def _github_contact(client: httpx.Client, row: dict[str, Any]) -> str | None:
    logins = []
    for url in _iter_urls(row):
        login = _github_login(url)
        if login and login not in logins:
            logins.append(login)
    for login in logins[:2]:
        email = _github_for_login(client, login)
        if email:
            return email
    return None


def _company_website(company: str, row: dict[str, Any] | None = None) -> str | None:
    if not company:
        return None
    try:
        with _web_src():
            from src.paths import company_key
            from src.store import get_company

            queries = [company]
            tokens = _company_tokens(company)
            if tokens:
                queries.append(tokens[0])
            seen = set()
            for query in queries:
                key = company_key(query)
                if key in seen:
                    continue
                seen.add(key)
                rec = get_company(key)
                if not isinstance(rec, dict):
                    continue
                overview = rec.get("overview") or {}
                resolved = rec.get("resolved") or {}
                site = overview.get("website") or resolved.get("website")
                if site:
                    return site
    except Exception:
        pass
    row = row if isinstance(row, dict) else {}
    for key in ("website", "company_website", "org_website"):
        url = str(row.get(key) or "").strip()
        if _origin(url):
            return url
    for url in _iter_urls(row):
        host = (urlparse(url).netloc or "").lower()
        if any(s in host for s in SKIP_HOST):
            continue
        if _host_matches_company(url, company):
            return url
    return None


def _probe_company_site(client: httpx.Client, company: str) -> str | None:
    tokens = _company_tokens(company)
    if not tokens:
        return None
    token = tokens[0]
    needles = [company.lower(), token]
    cands = [
        f"https://www.{token}.com",
        f"https://the{token}.com",
        f"https://www.the{token}.com",
        f"https://{token}.com",
    ]
    for url in cands:
        html = _fetch(client, url)
        if not html or len(html) < 400:
            continue
        low = html.lower()
        if any(n in low for n in needles if len(n) > 3):
            return url
    return None


def _ingest_saved(
    saved: dict[str, Any], name: str
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    emails: list[dict[str, str]] = []
    phones: list[dict[str, str]] = []
    company_emails: list[dict[str, str]] = []
    company_phones: list[dict[str, str]] = []
    profile = saved.get("profile") if isinstance(saved.get("profile"), dict) else {}
    for item in _as_list(profile.get("email_entries")):
        if not isinstance(item, dict):
            continue
        src = str(item.get("source") or "").strip().lower()
        if src in ("guessed", "guess"):
            continue
        value = _clean_email(item.get("value") or "")
        if src == "company_site" and value and _is_generic_email(value):
            _add_email(company_emails, value, "company_site")
            continue
        if src == "company_site":
            if not value or not _email_matches_name(value, name):
                continue
        _add_email(emails, item.get("value") or "", src or "saved")
    for item in _as_list(profile.get("phone_entries")):
        if not isinstance(item, dict):
            continue
        src = str(item.get("source") or "").strip().lower()
        if src in ("guessed", "guess", "company_site"):
            continue
        _add_phone(phones, item.get("value") or "", src or "saved")
    for item in _as_list(profile.get("company_email_entries")):
        if isinstance(item, dict):
            _add_email(company_emails, item.get("value") or "", str(item.get("source") or "company_site"))
        else:
            _add_email(company_emails, str(item), "company_site")
    for item in _as_list(profile.get("company_phone_entries")):
        if isinstance(item, dict):
            _add_phone(company_phones, item.get("value") or "", str(item.get("source") or "company_site"))
        else:
            _add_phone(company_phones, str(item), "company_site")
    if not emails:
        for item in _as_list(saved.get("emails")):
            cleaned = _clean_email(str(item))
            if cleaned and _is_generic_email(cleaned):
                _add_email(company_emails, cleaned, "company_site")
            else:
                _add_email(emails, str(item), "saved")
        cleaned = _clean_email(saved.get("email") or "")
        if cleaned and _is_generic_email(cleaned):
            _add_email(company_emails, cleaned, "company_site")
        else:
            _add_email(emails, saved.get("email") or "", "saved")
    if not phones:
        for item in _as_list(saved.get("phones")):
            _add_phone(phones, str(item), "saved")
        _add_phone(phones, saved.get("phone") or "", "saved")
    return emails, phones, company_emails, company_phones


def _saved_person(row: dict[str, Any]) -> dict[str, Any] | None:
    try:
        with _web_src():
            from src.store import get_person, person_key

            key = person_key(
                row.get("linkedin_profile_url") or row.get("url") or "",
                row.get("name") or "",
                row.get("current_company") or "",
            )
            return get_person(key)
    except Exception:
        return None


def _persist(
    row: dict[str, Any],
    emails: list[dict[str, str]],
    phones: list[dict[str, str]],
    company_emails: list[dict[str, str]],
    company_phones: list[dict[str, str]],
) -> None:
    try:
        with _web_src():
            from src.store import upsert_person

            snapshot = {}
            for key in (
                "name",
                "headline",
                "current_role",
                "current_company",
                "location",
                "about",
                "links",
                "twitter",
                "other_channels",
                "linkedin_profile_url",
                "url",
            ):
                val = row.get(key)
                if val in (None, "", []):
                    continue
                snapshot[key] = val
            snapshot.update(
                {
                    "email_entries": emails,
                    "phone_entries": phones,
                    "company_email_entries": company_emails,
                    "company_phone_entries": company_phones,
                    "company_emails": [item["value"] for item in company_emails],
                    "company_phones": [item["value"] for item in company_phones],
                }
            )
            if row.get("headline"):
                snapshot["headline"] = row.get("headline")
            if row.get("current_role"):
                snapshot["role"] = row.get("current_role")
                snapshot["current_role"] = row.get("current_role")
            if row.get("location"):
                snapshot["location"] = row.get("location")
            upsert_person(
                {
                    "linkedin_url": row.get("linkedin_profile_url") or row.get("url"),
                    "name": row.get("name"),
                    "company": row.get("current_company"),
                    "email": row.get("email"),
                    "phone": row.get("phone"),
                    "emails": [item["value"] for item in emails],
                    "phones": [item["value"] for item in phones],
                    "sources": list(dict.fromkeys(item["source"] for item in emails + phones + company_emails + company_phones)),
                    "profile": snapshot,
                }
            )
    except Exception:
        pass


def cached_profile(url: str) -> dict[str, Any] | None:
    try:
        with _web_src():
            from src.store import find_person_by_url, person_to_profile

            rec = find_person_by_url(url)
            if not rec:
                return None
            row = person_to_profile(rec)
            if not row.get("name"):
                return None
            return row
    except Exception:
        return None


def enrich_profile(row: dict[str, Any], hints: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(row, dict) or row.get("error") == "auth_required":
        return row
    hints = hints if isinstance(hints, dict) else {}
    if hints.get("name") and not row.get("name"):
        row["name"] = str(hints.get("name") or "").strip()
    if hints.get("company") and not row.get("current_company"):
        row["current_company"] = str(hints.get("company") or "").strip()
    if hints.get("role") and not row.get("current_role"):
        row["current_role"] = str(hints.get("role") or "").strip()
    if hints.get("location") and not row.get("location"):
        row["location"] = str(hints.get("location") or "").strip()
    saved = _saved_person(row) or {}
    name = str(row.get("name") or "")
    company = str(row.get("current_company") or "")
    emails, phones, company_emails, company_phones = _ingest_saved(saved, name)
    row["email"] = _clean_email(row.get("email") or "")
    row["phone"] = _clean_phone(row.get("phone") or "")
    if row.get("email") and _is_generic_email(str(row.get("email"))):
        _add_email(company_emails, row.get("email") or "", "company_site")
        row["email"] = None
    else:
        _add_email(emails, row.get("email") or "", "linkedin")
    _add_phone(phones, row.get("phone") or "", "linkedin")
    entered_email = _clean_email(hints.get("email") or "")
    entered_phone = _clean_phone(hints.get("phone") or "")
    _add_email(emails, entered_email or "", "entered")
    _add_phone(phones, entered_phone or "", "entered")
    if entered_email and not row.get("email"):
        row["email"] = entered_email
    if entered_phone and not row.get("phone"):
        row["phone"] = entered_phone

    with httpx.Client() as client:
        site = _company_website(company, row)
        if not site:
            site = _probe_company_site(client, company)
        if site:
            found_e, found_p = _scan_site(client, site)
            for item in found_e:
                if _is_generic_email(item):
                    _add_email(company_emails, item, "company_site")
                elif _email_matches_name(item, name):
                    _add_email(emails, item, "company_site")
            for item in found_p:
                _add_phone(company_phones, item, "company_site")
        for url in _link_urls(row):
            html = _fetch(client, url)
            found_e, found_p = _extract_from_html(html)
            for item in _emails_in_text(html):
                if item not in found_e:
                    found_e.append(item)
            company_page = bool(site and _origin(url) == _origin(site)) or _host_matches_company(url, company)
            for item in found_e:
                if _is_generic_email(item):
                    _add_email(company_emails, item, "company_site" if company_page else "profile_link")
                else:
                    _add_email(emails, item, "profile_link")
            for item in found_p:
                if company_page:
                    _add_phone(company_phones, item, "company_site")
                else:
                    _add_phone(phones, item, "profile_link")
            time.sleep(0.35)
        gh_email = _github_contact(client, row)
        if gh_email:
            _add_email(emails, gh_email, "github")

    personal = [e["value"] for e in emails if not _is_generic_email(e["value"])]
    if not row.get("email") and personal:
        row["email"] = personal[0]
    if not row.get("phone") and phones:
        row["phone"] = phones[0]["value"]
    row["emails"] = [item["value"] for item in emails]
    row["phones"] = [item["value"] for item in phones]
    row["email_entries"] = emails
    row["phone_entries"] = phones
    row["company_emails"] = [item["value"] for item in company_emails]
    row["company_phones"] = [item["value"] for item in company_phones]
    row["company_email_entries"] = company_emails
    row["company_phone_entries"] = company_phones
    _persist(row, emails, phones, company_emails, company_phones)
    return row
