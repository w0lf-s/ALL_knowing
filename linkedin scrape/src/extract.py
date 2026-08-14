import json
import os
import re
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlparse

from playwright.sync_api import Locator, Page, Response

from src.config import DEBUG_JSON, ensure_dirs

VOYAGER_URL_MARKERS = (
    "/voyager/api/identity/dash/profiles",
    "/profileView",
    "/profileContactInfo",
    "/voyager/api/graphql",
)

DECORATION_IDS = (
    "com.linkedin.voyager.dash.deco.identity.profile.FullProfileWithEntities-93",
    "com.linkedin.voyager.dash.deco.identity.profile.FullProfileWithEntities-76",
    "com.linkedin.voyager.dash.deco.identity.profile.FullProfileWithEntities-57",
    "com.linkedin.voyager.dash.deco.identity.profile.FullProfileWithEntities-35",
)


def _fast() -> bool:
    return os.getenv("HEADLESS", "").strip().lower() in {"1", "true", "yes"}


def _blank_result(url: str) -> dict[str, Any]:
    return {
        "url": url,
        "name": None,
        "headline": None,
        "current_role": None,
        "current_company": None,
        "location": None,
        "about": None,
        "email": None,
        "phone": None,
        "links": [],
        "twitter": None,
        "linkedin_profile_url": url.split("?")[0],
        "other_channels": [],
        "error": None,
    }


def _slug_from_url(url: str) -> str | None:
    path = urlparse(url).path.strip("/")
    parts = path.split("/")
    if len(parts) >= 2 and parts[0] == "in" and parts[1]:
        return unquote(parts[1])
    return None


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        for key in ("text", "value", "name", "localized", "title"):
            if key in value:
                return _clean_text(value.get(key))
        return None
    text = str(value).replace("\n", " ").strip()
    return text or None


def _merge_field(target: dict[str, Any], key: str, value: Any) -> None:
    if value is None:
        return
    if key == "links":
        incoming = value if isinstance(value, list) else [value]
        for item in incoming:
            if isinstance(item, dict):
                _add_link(
                    target,
                    item.get("url") or item.get("address") or item.get("websiteUrl"),
                    item.get("title") or item.get("type") or item.get("category") or item.get("label"),
                )
            else:
                _add_link(target, item, None)
        return
    if key == "other_channels":
        existing = target.get(key) or []
        if not isinstance(existing, list):
            existing = []
        incoming = value if isinstance(value, list) else [value]
        for item in incoming:
            cleaned = _clean_text(item)
            if cleaned and cleaned not in existing:
                existing.append(cleaned)
        target[key] = existing
        return
    if not target.get(key):
        cleaned = _clean_text(value)
        if cleaned:
            target[key] = cleaned


def _looks_like_profile_entity(item: dict[str, Any]) -> bool:
    type_name = str(item.get("$type") or item.get("_type") or "")
    if "Profile" in type_name and "Position" not in type_name:
        return True
    if item.get("firstName") and (item.get("lastName") is not None or item.get("headline")):
        return True
    return False


def _looks_like_position(item: dict[str, Any]) -> bool:
    type_name = str(item.get("$type") or item.get("_type") or "")
    if "Position" in type_name:
        return True
    return bool(item.get("title") and (item.get("companyName") or item.get("company")))


def _company_name_from_position(item: dict[str, Any]) -> str | None:
    return _first_present(
        _clean_text(item.get("companyName")),
        _clean_text(item.get("company")),
        _clean_text((item.get("company") or {}).get("name") if isinstance(item.get("company"), dict) else None),
    )


def _first_present(*values: str | None) -> str | None:
    for value in values:
        if value:
            return value
    return None


def _walk_objects(node: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        found.append(node)
        for value in node.values():
            found.extend(_walk_objects(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_walk_objects(value))
    return found


def _parse_voyager_profile(payload: Any) -> dict[str, Any]:
    parsed: dict[str, Any] = {
        "name": None,
        "headline": None,
        "current_role": None,
        "current_company": None,
        "location": None,
        "about": None,
    }
    if not isinstance(payload, (dict, list)):
        return parsed

    objects = _walk_objects(payload)
    profile = None
    for item in objects:
        if _looks_like_profile_entity(item):
            profile = item
            break
    if profile:
        first = _clean_text(profile.get("firstName")) or ""
        last = _clean_text(profile.get("lastName")) or ""
        full = f"{first} {last}".strip()
        _merge_field(parsed, "name", full or None)
        _merge_field(parsed, "headline", profile.get("headline"))
        _merge_field(
            parsed,
            "location",
            _first_present(
                _clean_text(profile.get("geoLocationName")),
                _clean_text(profile.get("locationName")),
                _clean_text(profile.get("geoLocation")),
                _clean_text((profile.get("location") or {}).get("countryCode") if isinstance(profile.get("location"), dict) else None),
            ),
        )
        about_value = _first_present(
            _clean_text(profile.get("summary")),
            _clean_text(profile.get("about")),
        )
        mini = profile.get("miniProfile")
        if isinstance(mini, dict) and not about_value:
            about_value = _clean_text(mini.get("occupation"))
        _merge_field(parsed, "about", about_value)

    for item in objects:
        if not _looks_like_position(item):
            continue
        end = item.get("timePeriod") or item.get("dateRange") or {}
        end_date = None
        if isinstance(end, dict):
            end_date = end.get("endDate") or end.get("end")
        if end_date:
            continue
        role = _clean_text(item.get("title"))
        company = _company_name_from_position(item)
        if role or company:
            _merge_field(parsed, "current_role", role)
            _merge_field(parsed, "current_company", company)
            break

    if not parsed.get("current_role") and parsed.get("headline"):
        role, company = _split_role_company(parsed.get("headline"))
        _merge_field(parsed, "current_role", role)
        _merge_field(parsed, "current_company", company)

    return parsed


def _parse_contact_payload(payload: Any) -> dict[str, Any]:
    parsed: dict[str, Any] = {
        "email": None,
        "phone": None,
        "links": [],
        "twitter": None,
        "linkedin_profile_url": None,
        "other_channels": [],
    }
    if not isinstance(payload, (dict, list)):
        return parsed

    objects = _walk_objects(payload)
    for item in objects:
        _merge_field(
            parsed,
            "email",
            item.get("emailAddress")
            or item.get("email")
            or item.get("emailAddressEntity")
            or (item.get("emailAddress") if isinstance(item.get("emailAddress"), str) else None),
        )
        if isinstance(item.get("emailAddress"), dict):
            _merge_field(parsed, "email", item["emailAddress"].get("emailAddress") or item["emailAddress"].get("email"))

        phones = item.get("phoneNumbers") or item.get("phones") or item.get("phoneNumber") or []
        if isinstance(phones, dict):
            phones = [phones]
        if isinstance(phones, list):
            for phone in phones:
                if isinstance(phone, dict):
                    _merge_field(
                        parsed,
                        "phone",
                        phone.get("number")
                        or phone.get("phoneNumber")
                        or phone.get("displayNumber"),
                    )
                else:
                    _merge_field(parsed, "phone", phone)

        websites = (
            item.get("websites")
            or item.get("website")
            or item.get("websitesUrl")
            or item.get("websiteUrl")
            or []
        )
        if isinstance(websites, dict):
            websites = [websites]
        if isinstance(websites, str):
            websites = [websites]
        if isinstance(websites, list):
            for site in websites:
                if isinstance(site, dict):
                    url_val = (
                        site.get("url")
                        or site.get("address")
                        or site.get("websiteUrl")
                        or site.get("localizedUrl")
                    )
                    title = (
                        _clean_text(site.get("type") or site.get("category") or site.get("label") or site.get("title"))
                        or "Website"
                    )
                    _add_link(parsed, url_val, title)
                else:
                    _add_link(parsed, site, "Website")

        twitters = item.get("twitterHandles") or item.get("twitter") or item.get("twitterHandle") or []
        if isinstance(twitters, str):
            _merge_field(parsed, "twitter", twitters)
            _add_link(parsed, twitters if str(twitters).startswith("http") else f"https://x.com/{twitters}", "Twitter")
        elif isinstance(twitters, dict):
            handle = twitters.get("name") or twitters.get("credential") or twitters.get("url")
            _merge_field(parsed, "twitter", handle)
            _add_link(parsed, twitters.get("url") or handle, "Twitter")
        elif isinstance(twitters, list):
            for handle in twitters:
                if isinstance(handle, dict):
                    name = handle.get("name") or handle.get("credential") or handle.get("url")
                    _merge_field(parsed, "twitter", name)
                    _add_link(parsed, handle.get("url") or name, "Twitter")
                else:
                    _merge_field(parsed, "twitter", handle)
                    _add_link(parsed, handle if str(handle).startswith("http") else f"https://x.com/{handle}", "Twitter")

        ims = item.get("ims") or item.get("connectedMessengerHandles") or []
        if isinstance(ims, list):
            for entry in ims:
                if isinstance(entry, dict):
                    provider = _clean_text(entry.get("provider") or entry.get("name"))
                    handle = _clean_text(entry.get("id") or entry.get("handle") or entry.get("value"))
                    if provider and handle:
                        _merge_field(parsed, "other_channels", f"{provider}: {handle}")

        address = item.get("address") or item.get("postalAddress")
        if isinstance(address, dict):
            formatted = _clean_text(address.get("formattedAddress") or address.get("address"))
            if formatted:
                _merge_field(parsed, "other_channels", f"Address: {formatted}")
        elif isinstance(address, str):
            _merge_field(parsed, "other_channels", f"Address: {address}")

    return parsed


def _payload_has_profile_signal(payload: Any) -> bool:
    parsed = _parse_voyager_profile(payload)
    return bool(parsed.get("name") or parsed.get("headline"))


def _is_interesting_response(url: str) -> bool:
    lower = url.lower()
    return any(marker in lower for marker in VOYAGER_URL_MARKERS)


def _attach_response_capture(page: Page, bucket: list[dict[str, Any]]) -> Callable[[Response], None]:
    def on_response(response: Response) -> None:
        try:
            url = response.url
            if not _is_interesting_response(url):
                return
            if response.status >= 400:
                return
            content_type = (response.headers.get("content-type") or "").lower()
            if "json" not in content_type and "javascript" not in content_type:
                return
            data = response.json()
            if "/graphql" in url.lower() and not _payload_has_profile_signal(data):
                contact = _parse_contact_payload(data)
                if not (contact.get("email") or contact.get("phone") or contact.get("links")):
                    return
            bucket.append({"url": url, "json": data})
        except Exception:
            return

    page.on("response", on_response)
    return on_response


def _detach_response_capture(page: Page, handler: Callable[[Response], None]) -> None:
    try:
        page.remove_listener("response", handler)
    except Exception:
        pass


def _merge_captured(bucket: list[dict[str, Any]], data: dict[str, Any]) -> None:
    for entry in bucket:
        url = entry.get("url") or ""
        payload = entry.get("json")
        if "contactinfo" in url.lower() or "contact-info" in url.lower():
            contact = _parse_contact_payload(payload)
            for key, value in contact.items():
                _merge_field(data, key, value)
            continue
        profile = _parse_voyager_profile(payload)
        for key, value in profile.items():
            _merge_field(data, key, value)
        contact = _parse_contact_payload(payload)
        for key, value in contact.items():
            _merge_field(data, key, value)


def _fetch_voyager_json(page: Page, path: str) -> Any | None:
    script = """
    async ({ path }) => {
      const match = document.cookie.match(/JSESSIONID="?([^";]+)"?/);
      if (!match) return null;
      const csrf = match[1];
      const response = await fetch(path, {
        credentials: "include",
        headers: {
          accept: "application/vnd.linkedin.normalized+json+2.1",
          "csrf-token": csrf,
          "x-restli-protocol-version": "2.0.0",
        },
      });
      if (!response.ok) {
        return { __error: true, status: response.status };
      }
      return await response.json();
    }
    """
    try:
        result = page.evaluate(script, {"path": path})
        if isinstance(result, dict) and result.get("__error"):
            return None
        return result
    except Exception:
        return None


def _fetch_profile_via_page(page: Page, slug: str) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for decoration in DECORATION_IDS:
        path = (
            "/voyager/api/identity/dash/profiles"
            f"?q=memberIdentity&memberIdentity={slug}"
            f"&decorationId={decoration}"
        )
        payload = _fetch_voyager_json(page, path)
        if not payload:
            continue
        profile = _parse_voyager_profile(payload)
        for key, value in profile.items():
            _merge_field(parsed, key, value)
        if parsed.get("name") or parsed.get("headline"):
            break

    alt = _fetch_voyager_json(page, f"/voyager/api/identity/profiles/{slug}/profileView")
    if alt:
        profile = _parse_voyager_profile(alt)
        for key, value in profile.items():
            _merge_field(parsed, key, value)
    return parsed


def _fetch_contact_via_page(page: Page, slug: str) -> dict[str, Any]:
    paths = [
        f"/voyager/api/identity/profiles/{slug}/profileContactInfo",
        f"/voyager/api/identity/profiles/{slug}/networkinfo",
        (
            "/voyager/api/identity/dash/profiles"
            f"?q=memberIdentity&memberIdentity={slug}"
            "&decorationId=com.linkedin.voyager.dash.deco.identity.profile.FullProfileWithEntities-93"
        ),
    ]
    parsed: dict[str, Any] = {
        "email": None,
        "phone": None,
        "links": [],
        "twitter": None,
        "linkedin_profile_url": None,
        "other_channels": [],
    }
    for path in paths:
        payload = _fetch_voyager_json(page, path)
        if not payload:
            continue
        contact = _parse_contact_payload(payload)
        for key, value in contact.items():
            _merge_field(parsed, key, value)
        if parsed.get("email") or parsed.get("links") or parsed.get("phone"):
            break
    return parsed


def _unwrap_href(href: str) -> str:
    if not href:
        return href
    cleaned = href.replace("&amp;", "&").strip()
    lower = cleaned.lower()
    if any(
        marker in lower
        for marker in (
            "linkedin.com/redir/redirect",
            "linkedin.com/safety/go",
            "linkedin.com/redir/unauthorized-redirect",
        )
    ):
        query = parse_qs(urlparse(cleaned).query)
        for key in ("url", "URL", "to", "dest", "destination"):
            target = query.get(key)
            if target:
                return unquote(unquote(target[0])).strip()
    return cleaned


def _emails_from_text(text: str) -> list[str]:
    if not text:
        return []
    found = re.findall(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", text)
    return [item for item in found if "linkedin.com" not in item.lower()]


def _normalize_link_url(value: str | None) -> str | None:
    text = _unwrap_href((value or "").strip())
    if not text:
        return None
    lower = text.lower()
    if lower.startswith(("mailto:", "tel:", "javascript:", "#")):
        return None
    if lower.startswith("//"):
        text = "https:" + text
        lower = text.lower()
    if not lower.startswith(("http://", "https://")):
        if re.fullmatch(r"(?:www\.)?[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+(?:/[^\s]*)?", text):
            text = "https://" + text.lstrip("/")
        else:
            return None
    return text.split("#")[0].rstrip("/")


def _title_from_text(text: str | None, fallback: str | None = None) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").replace("\n", " ")).strip()
    if cleaned:
        return cleaned
    if fallback:
        return fallback
    return "Link"


def _is_outbound_profile_link(href: str) -> bool:
    raw = (href or "").strip()
    lower = raw.lower()
    if not lower or lower.startswith(("mailto:", "tel:", "javascript:", "#")):
        return False
    if any(
        marker in lower
        for marker in (
            "linkedin.com/redir/redirect",
            "linkedin.com/safety/go",
            "linkedin.com/redir/unauthorized-redirect",
        )
    ):
        return True
    unwrapped = _unwrap_href(raw)
    lower_unwrapped = unwrapped.lower()
    if lower_unwrapped.startswith(("http://", "https://")):
        return "linkedin.com" not in lower_unwrapped and "lnkd.in" not in lower_unwrapped
    if re.fullmatch(
        r"(?:www\.)?[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+(?:/[^\s]*)?",
        unwrapped.strip(),
    ):
        return "linkedin.com" not in lower_unwrapped and "lnkd.in" not in lower_unwrapped
    return False


def _add_link(data: dict[str, Any], url: Any, title: Any = None) -> None:
    raw = str(url) if url is not None else ""
    if not _is_outbound_profile_link(raw):
        return
    normalized = _normalize_link_url(raw)
    if not normalized:
        return
    title_text = _title_from_text(
        str(title) if title is not None else None,
        fallback=normalized,
    )
    links = data.get("links")
    if not isinstance(links, list):
        links = []
        data["links"] = links
    for existing in links:
        if existing.get("url") == normalized:
            current_title = existing.get("title") or ""
            if title_text and title_text != normalized and (
                not current_title or current_title == normalized
            ):
                existing["title"] = title_text
            return
    links.append({"title": title_text, "url": normalized})


def _contact_overlay_url(profile_url: str) -> str:
    base = profile_url.split("?")[0].rstrip("/")
    if base.endswith("/overlay/contact-info"):
        return base + "/"
    return base + "/overlay/contact-info/"


def _parse_contact_dom(root: Locator, data: dict[str, Any]) -> None:
    try:
        mail = root.locator('a[href^="mailto:"]')
        for i in range(min(mail.count(), 5)):
            href = mail.nth(i).get_attribute("href") or ""
            email = href.replace("mailto:", "").split("?")[0].strip()
            _merge_field(data, "email", email)

        tel = root.locator('a[href^="tel:"]')
        for i in range(min(tel.count(), 5)):
            href = tel.nth(i).get_attribute("href") or ""
            _merge_field(data, "phone", href.replace("tel:", "").strip())

        modal_text = root.inner_text(timeout=3000)
        for email in _emails_from_text(modal_text):
            _merge_field(data, "email", email)
        _links_from_website_text(modal_text, data)

        links = root.locator(
            "a[href*='redir/redirect'], a[href*='safety/go'], a[href^='http'], a[href]"
        )
        for i in range(min(links.count(), 40)):
            link = links.nth(i)
            href = link.get_attribute("href") or ""
            link_text = ""
            try:
                link_text = (link.inner_text(timeout=800) or "").strip()
            except Exception:
                pass
            lower = href.lower()
            unwrapped = _unwrap_href(href)
            if lower.startswith("mailto:"):
                _merge_field(data, "email", href.replace("mailto:", "").split("?")[0])
                continue
            if lower.startswith("tel:"):
                _merge_field(data, "phone", href.replace("tel:", "").strip())
                continue
            if "linkedin.com/in/" in unwrapped.lower() and "/overlay/" not in unwrapped.lower():
                _merge_field(data, "linkedin_profile_url", unwrapped.split("?")[0])
                continue
            if "twitter.com" in unwrapped.lower() or "x.com" in unwrapped.lower():
                _merge_field(data, "twitter", unwrapped.split("?")[0])
            _add_link(data, href, link_text or None)
            for line in link_text.split("\n"):
                candidate = line.strip()
                if candidate:
                    _add_link(data, candidate, link_text.split("\n")[0].strip() or candidate)
    except Exception:
        pass


def _links_from_website_text(text: str, data: dict[str, Any]) -> None:
    if not text:
        return
    lower = text.lower()
    start = -1
    for marker in ("website", "websites", "web site"):
        idx = lower.find(marker)
        if idx >= 0:
            start = idx
            break
    if start < 0:
        return
    snippet = text[start : start + 600]
    for match in re.findall(
        r"https?://[^\s<>\"']+|(?:www\.)?[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+(?:/[^\s<>\"']*)?",
        snippet,
    ):
        if "@" in match:
            continue
        if "linkedin.com" in match.lower() or "lnkd.in" in match.lower():
            continue
        if match.lower() in {
            "website",
            "websites",
            "company",
            "personal",
            "blog",
            "portfolio",
            "other",
        }:
            continue
        _add_link(data, match, "Website")


def _collect_links_via_js(page: Page, scope: str = "contact") -> list[dict[str, str]]:
    script = """
    ({ scope }) => {
      const isRedirect = (href) => {
        const lower = (href || '').toLowerCase();
        return lower.includes('/redir/redirect') || lower.includes('/safety/go');
      };
      const isExternal = (href) => {
        const lower = (href || '').toLowerCase();
        if (!href) return false;
        if (lower.includes('linkedin.com') || lower.includes('lnkd.in')) return false;
        if (/^https?:\\/\\//i.test(href)) return true;
        return /^(?:www\\.)?[A-Za-z0-9-]+(?:\\.[A-Za-z0-9-]+)+(?:\\/\\S*)?$/.test(href);
      };

      let roots = [];
      if (scope === 'contact') {
        roots = [
          ...document.querySelectorAll('.artdeco-modal'),
          ...document.querySelectorAll('section.pv-contact-info'),
          ...document.querySelectorAll("div[aria-label*='Contact']"),
        ];
      } else if (scope === 'redirects') {
        roots = [
          ...document.querySelectorAll('main'),
          ...document.querySelectorAll('.artdeco-modal'),
          document.body,
        ].filter(Boolean);
      } else {
        roots = [
          ...document.querySelectorAll('section:has(#featured)'),
          ...document.querySelectorAll('section:has(#licenses_and_certifications)'),
          ...document.querySelectorAll('section:has(#about)'),
          ...document.querySelectorAll('section:has(#publications)'),
          ...document.querySelectorAll('section:has(#projects)'),
          ...document.querySelectorAll('#featured'),
          ...document.querySelectorAll('#licenses_and_certifications'),
          ...document.querySelectorAll('#about'),
          ...document.querySelectorAll('main'),
        ];
      }

      const seen = new Set();
      const results = [];
      for (const root of roots.filter(Boolean)) {
        for (const a of root.querySelectorAll('a[href]')) {
          const href = a.getAttribute('href') || a.href || '';
          if (!href || seen.has(href)) continue;
          if (scope === 'redirects') {
            if (!isRedirect(href)) continue;
          } else if (!(isRedirect(href) || isExternal(href))) {
            continue;
          }
          seen.add(href);
          results.push({
            href,
            text: (a.innerText || a.textContent || '').trim(),
          });
        }
      }
      return results;
    }
    """
    try:
        result = page.evaluate(script, {"scope": scope})
        if isinstance(result, list):
            return result
    except Exception:
        pass
    return []


def _apply_link_items(data: dict[str, Any], items: list[dict[str, str]]) -> None:
    for item in items:
        href = item.get("href") or ""
        text = item.get("text") or ""
        lower = href.lower()
        unwrapped = _unwrap_href(href)
        if lower.startswith("mailto:") or text.lower().startswith("mailto:"):
            _merge_field(data, "email", href.replace("mailto:", "").split("?")[0] or text)
            continue
        if lower.startswith("tel:"):
            _merge_field(data, "phone", href.replace("tel:", "").strip())
            continue
        if "linkedin.com/in/" in unwrapped.lower() and "/overlay/" not in unwrapped.lower():
            _merge_field(data, "linkedin_profile_url", unwrapped.split("?")[0])
            continue
        if "twitter.com" in unwrapped.lower() or "x.com" in unwrapped.lower():
            _merge_field(data, "twitter", unwrapped.split("?")[0])
        title = text.split("\n")[0].strip() if text else None
        _add_link(data, href, title)
        for line in text.split("\n"):
            candidate = line.strip()
            if candidate:
                _add_link(data, candidate, title or candidate)


def _collect_profile_links(page: Page, data: dict[str, Any]) -> None:
    try:
        page.evaluate("window.scrollTo(0, Math.floor(document.body.scrollHeight * 0.35))")
        page.wait_for_timeout(250 if _fast() else 800)
        page.evaluate("window.scrollTo(0, Math.floor(document.body.scrollHeight * 0.7))")
        page.wait_for_timeout(250 if _fast() else 800)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(250 if _fast() else 800)
    except Exception:
        pass
    _apply_link_items(data, _collect_links_via_js(page, scope="redirects"))
    _apply_link_items(data, _collect_links_via_js(page, scope="profile"))
    try:
        main_text = page.locator("main").inner_text(timeout=3000)
        _links_from_website_text(main_text, data)
    except Exception:
        pass


def _close_contact_overlay(page: Page) -> None:
    for selector in (
        '.artdeco-modal button[aria-label="Dismiss"]',
        '.artdeco-modal button.artdeco-modal__dismiss',
        'button[data-test-modal-close-btn]',
    ):
        try:
            btn = page.locator(selector)
            if btn.count() > 0 and btn.first.is_visible(timeout=800):
                btn.first.click(timeout=1500)
                page.wait_for_timeout(300)
                return
        except Exception:
            continue
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
    except Exception:
        pass


def _extract_dom_contact(page: Page, data: dict[str, Any], captured: list[dict[str, Any]]) -> None:
    profile_url = data.get("linkedin_profile_url") or data.get("url") or page.url
    before = len(captured)

    opened = False
    candidates = [
        page.locator('a[href*="overlay/contact-info"]'),
        page.locator('a[href*="contact-info"]'),
        page.get_by_role("link", name="Contact info"),
        page.locator('a:has-text("Contact info")'),
        page.get_by_text("Contact info", exact=True),
    ]
    for candidate in candidates:
        try:
            if candidate.count() == 0:
                continue
            target = candidate.first
            if not target.is_visible(timeout=600 if _fast() else 1200):
                continue
            target.click(timeout=4000)
            page.wait_for_timeout(400 if _fast() else 1500)
            opened = True
            break
        except Exception:
            continue

    if not opened:
        try:
            page.goto(_contact_overlay_url(str(profile_url)), wait_until="domcontentloaded", timeout=20000 if _fast() else 45000)
            page.wait_for_timeout(600 if _fast() else 2000)
            opened = True
        except Exception:
            opened = False

    if not opened:
        return

    try:
        page.wait_for_selector(
            ".artdeco-modal, section.pv-contact-info, a[href^='mailto:'], section:has-text('Email')",
            timeout=4000 if _fast() else 8000,
        )
    except Exception:
        pass
    page.wait_for_timeout(300 if _fast() else 1000)

    if len(captured) > before:
        _merge_captured(captured[before:], data)

    modal = page.locator(
        ".artdeco-modal:has-text('Contact'), "
        ".artdeco-modal:has-text('Email'), "
        "section.pv-contact-info, "
        "div.artdeco-modal__content, "
        ".artdeco-modal"
    )
    if modal.count() > 0:
        _parse_contact_dom(modal.first, data)
    else:
        _parse_contact_dom(page.locator("main, body"), data)

    _apply_link_items(data, _collect_links_via_js(page, scope="contact"))
    _apply_link_items(data, _collect_links_via_js(page, scope="redirects"))

    if not data.get("email") or not data.get("links"):
        try:
            body_text = page.locator(".artdeco-modal, section.pv-contact-info").first.inner_text(
                timeout=3000
            )
            for email in _emails_from_text(body_text):
                _merge_field(data, "email", email)
            _links_from_website_text(body_text, data)
        except Exception:
            pass

    _close_contact_overlay(page)

    if not _fast():
        try:
            page.goto(str(profile_url).split("?")[0], wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(1200)
        except Exception:
            pass
    _collect_profile_links(page, data)


def _split_role_company(headline: str | None) -> tuple[str | None, str | None]:
    if not headline:
        return None, None
    for sep in (" at ", " @ ", " | "):
        if sep.lower() in headline.lower():
            idx = headline.lower().find(sep.lower())
            left = headline[:idx].strip()
            right = headline[idx + len(sep) :].strip()
            return left or None, right or None
    return headline.strip() or None, None


def _safe_text(locator: Locator, timeout: int = 4000) -> str | None:
    try:
        locator.first.wait_for(state="attached", timeout=timeout)
        text = locator.first.inner_text(timeout=timeout).strip()
        return text or None
    except Exception:
        return None


def _first_text(page: Page, selectors: list[str], timeout: int = 4000) -> str | None:
    for selector in selectors:
        text = _safe_text(page.locator(selector), timeout=timeout)
        if text and text.lower() not in {"linkedin", "sign up", "join linkedin"}:
            return text
    return None


def _dismiss_noise(page: Page) -> None:
    selectors = [
        'button[aria-label="Dismiss"]',
        'button.msg-overlay-bubble-header__control',
        'button[data-test-modal-close-btn]',
        'button.artdeco-modal__dismiss',
        'button:has-text("Not now")',
        'button:has-text("Dismiss")',
        'button:has-text("No thanks")',
    ]
    for selector in selectors:
        try:
            buttons = page.locator(selector)
            count = min(buttons.count(), 5)
            for i in range(count):
                btn = buttons.nth(i)
                if btn.is_visible(timeout=400):
                    btn.click(timeout=1500)
                    page.wait_for_timeout(250)
        except Exception:
            continue
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
    except Exception:
        pass


def _page_looks_like_authwall(page: Page) -> bool:
    current = page.url.lower()
    if any(part in current for part in ("/login", "/authwall", "/checkpoint", "/uas/login")):
        return True
    try:
        body = page.locator("body").inner_text(timeout=3000).lower()
    except Exception:
        return False
    markers = (
        "sign in to view",
        "join linkedin",
        "agree & join",
        "authwall",
        "session expired",
    )
    return any(marker in body for marker in markers)


def _write_debug(page: Page, url: str, captured_count: int, data: dict[str, Any]) -> None:
    ensure_dirs()
    main_len = 0
    title = ""
    contact_links: list[dict[str, str]] = []
    try:
        title = page.title()
    except Exception:
        pass
    try:
        main_len = len(page.locator("main").inner_text(timeout=2000))
    except Exception:
        try:
            main_len = len(page.locator("body").inner_text(timeout=2000))
        except Exception:
            main_len = 0
    try:
        contact_links = _collect_links_via_js(page, scope="contact")[:20]
    except Exception:
        contact_links = []
    DEBUG_JSON.write_text(
        json.dumps(
            {
                "url": url,
                "final_url": page.url,
                "title": title,
                "captured_endpoint_count": captured_count,
                "main_text_length": main_len,
                "name": data.get("name"),
                "headline": data.get("headline"),
                "links": data.get("links"),
                "email": data.get("email"),
                "contact_links": contact_links,
                "error": data.get("error"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _extract_dom_profile(page: Page, data: dict[str, Any]) -> None:
    _dismiss_noise(page)
    try:
        page.evaluate("window.scrollTo(0, Math.floor(document.body.scrollHeight * 0.4))")
        page.wait_for_timeout(800)
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(500)
    except Exception:
        pass

    _merge_field(
        data,
        "name",
        _first_text(
            page,
            [
                "main h1",
                "h1.text-heading-xlarge",
                "h1.break-words",
                ".pv-text-details__left-panel h1",
                "h1",
            ],
        ),
    )
    _merge_field(
        data,
        "headline",
        _first_text(
            page,
            [
                "main div.text-body-medium.break-words",
                "div.text-body-medium.break-words",
                ".pv-text-details__left-panel .text-body-medium",
            ],
        ),
    )
    _merge_field(
        data,
        "location",
        _first_text(
            page,
            [
                "main span.text-body-small.inline.t-black--light.break-words",
                "span.text-body-small.inline.t-black--light.break-words",
                ".pv-text-details__left-panel .text-body-small",
            ],
        ),
    )
    _merge_field(
        data,
        "about",
        _first_text(
            page,
            [
                "section:has(#about) div.inline-show-more-text span[aria-hidden='true']",
                "section:has(#about) .inline-show-more-text",
                "#about ~ div .full-width span[aria-hidden='true']",
            ],
        ),
    )

    if not data.get("current_role") or not data.get("current_company"):
        role = None
        company = None
        try:
            section = page.locator("section:has(#experience), #experience").first
            item = section.locator("li.artdeco-list__item, li").first
            role = _safe_text(item.locator(".t-bold span[aria-hidden='true'], .t-bold span"))
            company = _safe_text(item.locator(".t-14.t-normal span[aria-hidden='true'], span.t-14.t-normal"))
            if company and "·" in company:
                company = company.split("·")[0].strip() or None
        except Exception:
            pass
        if not role and not company:
            role, company = _split_role_company(data.get("headline"))
        _merge_field(data, "current_role", role)
        _merge_field(data, "current_company", company)


def extract_profile(page: Page, url: str) -> dict[str, Any]:
    data = _blank_result(url)
    captured: list[dict[str, Any]] = []
    handler = _attach_response_capture(page, captured)
    slug = _slug_from_url(url)

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000 if _fast() else 60000)
        page.wait_for_timeout(700 if _fast() else 2500)
        if not _fast():
            try:
                page.wait_for_load_state("networkidle", timeout=12000)
            except Exception:
                pass
            page.wait_for_timeout(1500)

        if _page_looks_like_authwall(page):
            data["error"] = "auth_required"
            _write_debug(page, url, len(captured), data)
            return data

        _merge_captured(captured, data)

        if slug and not (data.get("name") and data.get("headline")):
            fetched = _fetch_profile_via_page(page, slug)
            for key, value in fetched.items():
                _merge_field(data, key, value)

        if slug and (not data.get("email") or not data.get("links")):
            contact = _fetch_contact_via_page(page, slug)
            for key, value in contact.items():
                _merge_field(data, key, value)

        missing_core = not data.get("name") or not data.get("headline")
        if missing_core:
            try:
                page.wait_for_selector("main h1, h1.text-heading-xlarge, h1.break-words", timeout=4000 if _fast() else 8000)
            except Exception:
                pass
            _extract_dom_profile(page, data)

        _extract_dom_contact(page, data, captured)
        if not data.get("links"):
            _collect_profile_links(page, data)

        if not data.get("name"):
            if _page_looks_like_authwall(page):
                data["error"] = "soft_authwall"
            else:
                data["error"] = "profile_not_rendered"
            _write_debug(page, url, len(captured), data)
        elif not data.get("links"):
            _write_debug(page, url, len(captured), data)
        elif not data.get("headline") and not data.get("current_role"):
            _write_debug(page, url, len(captured), data)

    except Exception as exc:
        data["error"] = str(exc)
        try:
            _write_debug(page, url, len(captured), data)
        except Exception:
            pass
    finally:
        _detach_response_capture(page, handler)

    return data


def is_successful_row(row: dict[str, Any]) -> bool:
    if row.get("error"):
        return False
    return bool(row.get("name"))
