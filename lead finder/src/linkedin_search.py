from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, unquote

from src.path_swap import linkedin_src_path

_PROFILE_RE = re.compile(
    r"https?://(?:www\.)?linkedin\.com/in/[A-Za-z0-9\-_%]+/?",
    re.IGNORECASE,
)
_SKIP_LINES = {
    "connect",
    "follow",
    "message",
    "pending",
    "view",
    "1st",
    "2nd",
    "3rd",
    "3rd+",
    "2nd+",
    "1st+",
    "• 1st",
    "• 2nd",
    "• 3rd",
    "contact info",
    "view full profile",
    "view profile",
    "see all people results",
    "message",
    "more",
    "current:",
    "past:",
}
_DEGREE_LINE_RE = re.compile(r"^[•·\-–—]?\s*\d+(?:st|nd|rd|th)\+?\s*$", re.I)
_UI_JUNK_LINE_RE = re.compile(
    r"^(contact info|view full profile|view profile|see all|connect|follow|message|pending|more profiles|status is .+)$",
    re.I,
)
_EXTRACT_JS = """() => {
    const textOf = (el) => (el && (el.innerText || el.textContent) || '').trim();
    const cardKey = (href) => {
        const part = (href.split('/in/')[1] || '').split(/[/?#]/)[0];
        return (part || '').replace(/[^a-zA-Z0-9_-]/g, '').slice(0, 80);
    };
    const isMutual = (t) => /mutual connection|mutual connections| and \\d+ other/i.test(t || '');
    const isDegree = (t) => /^[•·\\-–—]?\\s*\\d+(?:st|nd|rd|th)\\+?\\s*$/i.test((t || '').trim());
    const isAction = (t) => /^(message|connect|follow|pending|view profile|view full profile|contact info)$/i.test((t || '').trim());
    const cleanName = (raw) => String(raw || '').replace(/\\s*[•·].*$/, '').replace(/\\s+\\d+(?:st|nd|rd|th)\\+?$/i, '').trim();
    const visibleText = (el) => {
        if (!el) return '';
        const vis = el.querySelector('span[aria-hidden="true"]');
        if (vis) return textOf(vis);
        return textOf(el);
    };
    const skipImgUrl = (u) => !u || /^data:image\\/gif/i.test(u) || /ghost|sprite|emoji|company-logo|organization-logo|hashtag|static\\.licdn\\.com\\/aero/i.test(u);
    const urlFromImg = (img) => {
        if (!img) return '';
        const delayed = img.getAttribute('data-delayed-url') || img.getAttribute('data-li-src') || img.getAttribute('data-ghost-url') || '';
        const srcset = img.getAttribute('srcset') || '';
        let best = '';
        let bestW = 0;
        for (const part of srcset.split(',')) {
            const bits = part.trim().split(/\\s+/);
            const u = bits[0] || '';
            const w = parseInt((bits[1] || '0').replace('w', ''), 10) || 0;
            if (u && w >= bestW) { best = u; bestW = w; }
        }
        const src = img.currentSrc || img.getAttribute('src') || '';
        for (const u of [delayed, best, src]) {
            if (!skipImgUrl(u)) return u;
        }
        return '';
    };
    const pickCardPhotoEl = (card) => {
        if (!card) return null;
        const wraps = card.querySelectorAll('.entity-result__universal-image, .entity-result__image, .ivm-image-view-model, [class*="EntityPhoto"], .presence-entity');
        for (const wrap of wraps) {
            for (const img of wrap.querySelectorAll('img')) {
                if (urlFromImg(img) || (img.naturalWidth && img.naturalWidth >= 16)) return img;
            }
            const img = wrap.querySelector('img');
            if (img) return img;
        }
        for (const img of card.querySelectorAll('img')) {
            const u = urlFromImg(img);
            if (u && /licdn\\.com|data:image\\//i.test(u)) return img;
        }
        return null;
    };
    const headlineFromLines = (lines, personName) => {
        let past = false;
        for (const ln of lines) {
            if (!past) {
                if (cleanName(ln).toLowerCase() === cleanName(personName).toLowerCase()) past = true;
                continue;
            }
            const low = ln.toLowerCase();
            if (isDegree(ln) || isAction(low)) continue;
            if (isMutual(ln)) continue;
            if (personName && low === personName.toLowerCase()) continue;
            if (ln.includes('|') || /\\bat\\b/i.test(ln) || ln.length >= 12) return ln;
        }
        return '';
    };
    const locationFromLines = (lines, personName) => {
        let past = false;
        for (const ln of lines) {
            if (!past) {
                if (cleanName(ln).toLowerCase() === cleanName(personName).toLowerCase()) past = true;
                continue;
            }
            if (isDegree(ln) || isAction(ln.toLowerCase()) || isMutual(ln)) continue;
            if (ln.includes(',')) return ln;
        }
        return '';
    };
    const slugOf = (href) => ((href || '').split('/in/')[1] || '').split(/[/?#]/)[0].toLowerCase();
    const profileSlugs = (root) => {
        const set = new Set();
        if (!root) return set;
        for (const a of root.querySelectorAll('a[href*="/in/"]')) {
            if (isMutual(textOf(a))) continue;
            const s = slugOf(a.href || '');
            if (s) set.add(s);
        }
        return set;
    };
    const findCard = (link) => {
        const close = link.closest('li.reusable-search__result-container, [data-chameleon-result-urn], [data-view-name="search-entity-result"], li.entity-result, .entity-result, li[class*="result"]');
        if (close && profileSlugs(close).size <= 1) return close;
        const li = link.closest('li');
        if (li && profileSlugs(li).size <= 1) return li;
        let best = link.parentElement;
        let n = link.parentElement;
        for (let i = 0; i < 8 && n; i++) {
            const slugs = profileSlugs(n);
            if (slugs.size > 1) break;
            const r = n.getBoundingClientRect();
            if (r.height >= 48 && r.width >= 180) best = n;
            n = n.parentElement;
        }
        return best;
    };
    const parseAnchor = (link, minY) => {
        if (link.closest('aside, nav, header, footer')) return null;
        const href = (link.href || '').split('?')[0];
        if (!href.includes('/in/')) return null;
        const blob = textOf(link);
        if (isMutual(blob)) return null;
        let name = '';
        const hidden = link.querySelector('span[aria-hidden="true"]');
        if (hidden) name = cleanName(hidden.textContent || '');
        if (!name) name = cleanName(blob.split('\\n')[0]);
        if (!name || name.length < 2 || isMutual(name)) return null;
        const card = findCard(link);
        if (!card) return null;
        if (minY) {
            const y = (card.getBoundingClientRect().top || 0) + window.scrollY;
            if (y < minY - 12) return null;
        }
        const lines = textOf(card).split('\\n').map((s) => s.trim()).filter(Boolean);
        const key = cardKey(href);
        card.setAttribute('data-zuntra-card', key);
        let headline = '';
        for (const s of ['.entity-result__primary-subtitle', '[class*="primary-subtitle"]', '.artdeco-entity-lockup__subtitle']) {
            const el = card.querySelector(s);
            const t = visibleText(el);
            if (t) { headline = t; break; }
        }
        if (!headline) headline = headlineFromLines(lines, name);
        let location = '';
        for (const s of ['.entity-result__secondary-subtitle', '[class*="secondary-subtitle"]', '.artdeco-entity-lockup__caption']) {
            const el = card.querySelector(s);
            const t = visibleText(el);
            if (t) { location = t; break; }
        }
        if (!location) location = locationFromLines(lines, name);
        let photo = '';
        const photoEl = pickCardPhotoEl(card);
        if (photoEl) {
            photoEl.setAttribute('data-zuntra-photo', key);
            photo = urlFromImg(photoEl);
        }
        return { href, name, key, lines, photo, headline, location };
    };
    const headings = [...document.querySelectorAll('h2, h3')];
    const peopleHeading = headings.find((h) => /^people$/i.test(textOf(h)));
    let resultRoot = document.querySelector('.search-results-container, ul.reusable-search__entity-result-list');
    let minY = 0;
    if (peopleHeading) {
        minY = peopleHeading.getBoundingClientRect().top + window.scrollY;
        let n = peopleHeading.parentElement;
        for (let i = 0; i < 10 && n; i++) {
            if (n.querySelectorAll('a[href*="/in/"]').length >= 1) {
                resultRoot = n;
                break;
            }
            n = n.parentElement;
        }
    }
    if (!resultRoot) resultRoot = document.querySelector('main') || document.body;
    const seen = new Set();
    const out = [];
    const push = (row) => {
        if (!row) return;
        const slug = ((row.href || '').split('/in/')[1] || '').split('/')[0].toLowerCase();
        if (!slug || seen.has(slug)) return;
        seen.add(slug);
        out.push(row);
    };
    for (const link of resultRoot.querySelectorAll('a[href*="/in/"]')) push(parseAnchor(link, minY));
    return out;
}"""
_HEADER_JS = """(slug) => {
    const want = String(slug || '').toLowerCase().replace(/[-_]/g, '');
    const path = (location.pathname || '').toLowerCase().replace(/[-_]/g, '');
    if (want && path.indexOf('/in/' + want) === -1 && path.indexOf(want) === -1) {
        return { headline: '', location: '', company: '', photo: '', banner: '' };
    }
    const h1 = document.querySelector('main h1, h1.text-heading-xlarge, h1');
    const topCard = () => {
        if (!h1) return document.querySelector('main');
        let n = h1.parentElement;
        for (let i = 0; i < 14 && n; i++) {
            if (n.querySelector && n.querySelector('.profile-background-image, .pv-top-card-profile-picture, img[src*="displaybackground"], img[src*="profile-displayphoto"], img[srcset*="profile-displayphoto"]')) {
                return n;
            }
            n = n.parentElement;
        }
        return h1.closest('section') || document.querySelector('main');
    };
    const top = topCard();
    const visibleText = (el) => {
        if (!el) return '';
        const vis = el.querySelector('span[aria-hidden="true"]');
        const t = ((vis && vis.textContent) || el.innerText || el.textContent || '').trim();
        return t;
    };
    const pickText = (root, sels) => {
        const scope = root || document;
        for (const s of sels) {
            const el = scope.querySelector(s);
            const t = visibleText(el);
            if (t) return t;
        }
        return '';
    };
    let company = '';
    const expItem = document.querySelector('section:has(#experience) li, #experience ~ * li');
    if (expItem) {
        const coEl = expItem.querySelector('.t-14.t-normal span[aria-hidden="true"], span.t-14.t-normal');
        if (coEl) company = visibleText(coEl).split('·')[0].trim();
    }
    const skipImgUrl = (u) => !u || /^data:image\\/gif/i.test(u) || /ghost|sprite|emoji|static\\.licdn\\.com\\/aero/i.test(u);
    const urlFromImg = (img) => {
        if (!img) return '';
        const delayed = img.getAttribute('data-delayed-url') || img.getAttribute('data-li-src') || '';
        const srcset = img.getAttribute('srcset') || '';
        let best = '';
        let bestW = 0;
        for (const part of srcset.split(',')) {
            const bits = part.trim().split(/\\s+/);
            const u = bits[0] || '';
            const w = parseInt((bits[1] || '0').replace('w', ''), 10) || 0;
            if (u && w >= bestW) { best = u; bestW = w; }
        }
        const src = img.currentSrc || img.getAttribute('src') || '';
        for (const u of [delayed, best, src]) {
            if (!skipImgUrl(u)) return u;
        }
        return '';
    };
    const pickPhoto = () => {
        if (!top) return '';
        for (const s of [
            'img.pv-top-card-profile-picture__image',
            'button.pv-top-card-profile-picture img',
            '.pv-top-card-profile-picture img',
            'button[aria-label*="profile photo" i] img',
            'img[src*="profile-displayphoto"]',
            'img[srcset*="profile-displayphoto"]',
        ]) {
            const el = top.querySelector(s);
            if (!el) continue;
            const img = el.matches('img') ? el : el.querySelector('img');
            const u = urlFromImg(img);
            if (u) return u;
        }
        return '';
    };
    const pickBanner = () => {
        const root = top || document.querySelector('main') || document.body;
        if (!root) return '';
        const photoRe = /profile-displayphoto|framedphoto|ghost|sprite|emoji/i;
        const coverRe = /profile-displaybackground|displaybackground|profile-background|backgroundimage|16aq/i;
        const topImgs = [...root.querySelectorAll('img')].filter((img) => {
            const r = img.getBoundingClientRect();
            return r.width >= 160 && r.height >= 32 && r.top < 560;
        });
        for (const img of topImgs) {
            const src = urlFromImg(img);
            const set = img.getAttribute('srcset') || '';
            if ((coverRe.test(src) || coverRe.test(set)) && !photoRe.test(src)) return src;
        }
        for (const img of topImgs) {
            const r = img.getBoundingClientRect();
            const src = urlFromImg(img);
            if (!src || photoRe.test(src)) continue;
            if (r.width >= r.height * 1.55) return src;
        }
        for (const el of root.querySelectorAll('div, section, span')) {
            const r = el.getBoundingClientRect();
            if (r.width < 220 || r.height < 36 || r.height > 380 || r.top > 520) continue;
            const bg = getComputedStyle(el).backgroundImage || '';
            const m = bg.match(/url\\(["']?(.+?)["']?\\)/);
            if (m && m[1] && !m[1].startsWith('data:') && !photoRe.test(m[1])) return m[1];
        }
        return '';
    };
    return {
        headline: pickText(top, [
            'div.text-body-medium.break-words',
            '.pv-text-details__left-panel .text-body-medium',
        ]),
        location: pickText(top, [
            'span.text-body-small.inline.t-black--light.break-words',
            '.pv-text-details__left-panel .text-body-small',
        ]),
        company,
        photo: pickPhoto(),
        banner: pickBanner(),
    };
}"""
_IMAGE_DATA_JS = """async (url) => {
    if (!url) return '';
    if (url.startsWith('data:')) return url;
    try {
        const res = await fetch(url, { credentials: 'include' });
        if (!res.ok) return '';
        const blob = await res.blob();
        return await new Promise((resolve) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result || '');
            reader.onerror = () => resolve('');
            reader.readAsDataURL(blob);
        });
    } catch (_) {
        return '';
    }
}"""


def _normalize_profile_url(url: str) -> str | None:
    match = _PROFILE_RE.search(url or "")
    if not match:
        return None
    cleaned = match.group(0).split("?")[0].rstrip("/")
    if cleaned.lower().endswith("/in"):
        return None
    return cleaned


def _card_key(url: str) -> str:
    part = unquote((url or "").split("/in/")[-1].split("/")[0].split("?")[0])
    return re.sub(r"[^a-zA-Z0-9_-]", "", part)[:80]


def _useful_line(text: str, name: str) -> bool:
    low = (text or "").strip().lower()
    if not low or len(low) > 90:
        return False
    if low in _SKIP_LINES:
        return False
    if _DEGREE_LINE_RE.match(low):
        return False
    if _UI_JUNK_LINE_RE.match(low):
        return False
    if name and low == name.strip().lower():
        return False
    if low.startswith("http"):
        return False
    return True


def _headline_from_lines(useful: list[str]) -> str:
    for ln in useful:
        if _DEGREE_LINE_RE.match(ln.strip()):
            continue
        if "|" in ln or re.search(r"\bat\b", ln, re.I):
            return ln
        if len(ln) >= 12:
            return ln
    return ""


def _clean_text(text: str) -> str:
    s = str(text or "").strip()
    if not s:
        return ""
    parts = [p.strip() for p in re.split(r"[\n\r]+", s) if p.strip()]
    if len(parts) >= 2 and parts[0] == parts[1]:
        s = parts[0]
    compact = re.sub(r"\s+", " ", s)
    n = len(compact)
    if n >= 16:
        if n % 2 == 0 and compact[: n // 2] == compact[n // 2 :]:
            s = compact[: n // 2].strip()
        elif compact[n // 2 : n // 2 + 1] == " " and compact[: n // 2] == compact[n // 2 + 1 :]:
            s = compact[: n // 2].strip()
        else:
            s = compact
    else:
        s = compact
    if _DEGREE_LINE_RE.match(s) or _UI_JUNK_LINE_RE.match(s):
        return ""
    return s


def _merge_text_field(item: dict[str, Any], key: str, value: str) -> None:
    cleaned = _clean_text(value)
    if not cleaned:
        return
    old = _clean_text(str(item.get(key) or ""))
    if not old:
        item[key] = cleaned
        return
    if key == "headline" and (not old or _DEGREE_LINE_RE.match(old) or len(cleaned) > len(old)):
        item[key] = cleaned


def _companies_from_headline(headline: str) -> list[str]:
    parts = re.split(r"\bat\b", headline or "", flags=re.I)
    if len(parts) < 2:
        return []
    co = parts[-1].strip(" -|")
    if not co or len(co) >= 80:
        return []
    cleaned = _clean_text(co)
    return [cleaned] if cleaned else []


def _from_lines(lines: list[str], name: str) -> tuple[str, str, list[str]]:
    useful = [ln for ln in lines if _useful_line(ln, name)]
    headline = _headline_from_lines(useful)
    location = ""
    for ln in useful[1:]:
        if "," in ln or re.search(r"\b(india|bengaluru|bangalore|mumbai|delhi|hyderabad|pune|chennai|kolkata|remote)\b", ln, re.I):
            location = ln
            break
    companies: list[str] = []
    companies.extend(_companies_from_headline(headline))
    return headline, location, companies[:4]


def _jpeg_data(raw: bytes | None) -> str:
    if not raw:
        return ""
    return "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")


def _nav_failed(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(
        token in text
        for token in ("timeout", "navigating to", "waiting until", "net::err", "interrupted")
    )


def _page_matches_url(page: Any, url: str) -> bool:
    try:
        current = str(page.url or "").lower()
    except Exception:
        return False
    want = str(url or "").lower()
    if "/in/" in want:
        slug = re.sub(
            r"[^a-z0-9]",
            "",
            unquote(want.split("/in/")[-1].split("/")[0].split("?")[0]),
        )
        path = re.sub(r"[^a-z0-9]", "", current)
        return bool(slug and slug in path)
    return "linkedin.com" in current


def _safe_goto(page: Any, url: str, timeout: int = 60000) -> None:
    last: BaseException | None = None
    want = str(url)
    for wait in ("domcontentloaded", "commit"):
        try:
            page.goto(want, wait_until=wait, timeout=timeout)
            return
        except Exception as exc:
            last = exc
            if _page_matches_url(page, want):
                return
    if last and _nav_failed(last):
        raise RuntimeError("LinkedIn took too long to load. Try again.") from None
    raise RuntimeError("Could not open LinkedIn. Try again.") from None


def _shot_locator(loc: Any, max_h: int = 360) -> str:
    try:
        if loc.count() == 0:
            return ""
        loc.scroll_into_view_if_needed(timeout=2500)
        loc.page.wait_for_timeout(700)
        box = loc.bounding_box()
        if not box or box.get("width", 0) < 40 or box.get("height", 0) < 40:
            return ""
        kwargs: dict[str, Any] = {"type": "jpeg", "quality": 58}
        h = float(box.get("height") or 0)
        w = float(box.get("width") or 0)
        if h > max_h:
            kwargs["clip"] = {"x": 0, "y": 0, "width": int(w), "height": int(max_h)}
        try:
            return _jpeg_data(loc.screenshot(**kwargs))
        except Exception:
            kwargs.pop("clip", None)
            return _jpeg_data(loc.screenshot(**kwargs))
    except Exception:
        return ""


def _search_url(name: str, company: str, title: str = "", location: str = "") -> str:
    keywords = " ".join(part for part in (name, company, title, location) if part).strip()
    url = f"https://www.linkedin.com/search/results/all/?keywords={quote_plus(keywords)}"
    if title:
        url += f"&titleFreeText={quote_plus(title.strip())}"
    return url


def _click_people_show_all(page: Any) -> bool:
    try:
        clicked = page.evaluate(
            """() => {
                const textOf = (el) => (el && (el.innerText || el.textContent) || '').trim();
                const isShowAll = (el) => {
                    const t = (textOf(el) + ' ' + (el.getAttribute('aria-label') || '')).toLowerCase();
                    if (!/show all|see all people/.test(t)) return false;
                    if (/posts|companies|jobs|groups|events|products/.test(t)) return false;
                    return true;
                };
                const headings = [...document.querySelectorAll('h2, h3')];
                const people = headings.find((h) => /^people$/i.test(textOf(h)));
                if (people) {
                    let root = people.parentElement;
                    for (let i = 0; i < 12 && root; i++) {
                        const hit = [...root.querySelectorAll('a, button')].find(isShowAll);
                        if (hit) { hit.click(); return true; }
                        root = root.parentElement;
                    }
                }
                const fallback = [...document.querySelectorAll('a, button')].find(isShowAll);
                if (fallback && !fallback.closest('aside')) { fallback.click(); return true; }
                return false;
            }"""
        )
        return bool(clicked)
    except Exception:
        return False


def _open_people_show_all(page: Any) -> None:
    try:
        page.wait_for_timeout(1800)
        try:
            page.wait_for_selector('h2, h3, a[href*="/in/"]', timeout=12000)
        except Exception:
            pass
        if _click_people_show_all(page):
            page.wait_for_timeout(2200)
            try:
                page.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception:
                pass
            page.wait_for_timeout(1600)
            return
        tab = page.locator(
            'button:has-text("People"), a[href*="/search/results/people"]:has-text("People")'
        ).first
        if tab.count() > 0:
            try:
                tab.click(timeout=2500)
                page.wait_for_timeout(2000)
            except Exception:
                pass
        if _click_people_show_all(page):
            page.wait_for_timeout(2200)
            try:
                page.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception:
                pass
            page.wait_for_timeout(1600)
    except Exception:
        return


def _ensure_global_search(page: Any) -> None:
    try:
        page.wait_for_timeout(800)
        for deg in ("3rd+", "2nd"):
            btn = page.locator(f'button:has-text("{deg}")').first
            if btn.count() == 0:
                continue
            try:
                pressed = (btn.get_attribute("aria-pressed") or "").lower()
                if pressed in ("true", "1") or "active" in (btn.get_attribute("class") or "").lower():
                    continue
                if btn.is_visible():
                    btn.click(timeout=1500)
                    page.wait_for_timeout(400)
            except Exception:
                continue
        page.wait_for_timeout(600)
    except Exception:
        return


def _url_to_data(page: Any, url: str) -> str:
    src = str(url or "").strip()
    if not src:
        return ""
    if src.startswith("data:"):
        return src
    try:
        result = page.evaluate(_IMAGE_DATA_JS, src)
        return str(result or "").strip()
    except Exception:
        return ""


def _download_image(page: Any, url: str) -> str:
    src = str(url or "").strip()
    if not src:
        return ""
    if src.startswith("data:"):
        return src
    try:
        resp = page.context.request.get(src, timeout=15000)
        if resp.ok:
            body = resp.body()
            if body:
                return _jpeg_data(body)
    except Exception:
        pass
    return _url_to_data(page, src)


def _wake_lazy_images(page: Any) -> None:
    try:
        page.evaluate(
            """() => {
                document.querySelectorAll('img[data-delayed-url], img[data-li-src]').forEach((img) => {
                    const u = img.getAttribute('data-delayed-url') || img.getAttribute('data-li-src') || '';
                    if (u) img.src = u;
                });
            }"""
        )
    except Exception:
        return


def _header_matches(page: Any, name: str, slug: str, loose: bool = False) -> bool:
    try:
        path = re.sub(r"[^a-z0-9]", "", (page.url or "").lower())
        want_slug = re.sub(r"[^a-z0-9]", "", slug or "")
        if want_slug and want_slug not in path:
            return False
        h1 = page.locator("main h1, h1").first
        if h1.count() == 0:
            return False
        text = re.sub(r"\s+", " ", h1.inner_text() or "").strip().lower()
        text = re.split(r"[•·|]", text)[0].strip()
        first = ((name or "").strip().split() or [""])[0].lower()
        if first and len(first) >= 2 and first not in text:
            return bool(loose and want_slug)
        return True
    except Exception:
        return False


def _top_card_locator(page: Any) -> Any | None:
    h1 = page.locator("main h1").first
    if h1.count() == 0:
        return None
    loc = h1.locator("xpath=ancestor::*[.//*[contains(@class,'profile-background-image') or contains(@class,'pv-top-card-profile-picture')]][1]")
    try:
        if loc.count() > 0:
            return loc
    except Exception:
        pass
    fallback = h1.locator("xpath=ancestor::section[1]")
    try:
        if fallback.count() > 0:
            return fallback
    except Exception:
        pass
    return None


def _profile_photo_shot(page: Any) -> str:
    root = _top_card_locator(page)
    if root is None:
        return ""
    for sel in (
        "img.pv-top-card-profile-picture__image",
        "button.pv-top-card-profile-picture img",
        ".pv-top-card-profile-picture img",
        "img[src*='profile-displayphoto']",
    ):
        try:
            loc = root.locator(sel).first
            shot = _shot_locator(loc, max_h=240)
            if shot:
                return shot
        except Exception:
            continue
    return ""


def _profile_banner_shot(page: Any) -> str:
    try:
        page.evaluate("() => window.scrollTo(0, 0)")
        page.wait_for_timeout(250)
    except Exception:
        pass
    try:
        box = page.evaluate(
            """() => {
                const h1 = document.querySelector('main h1, h1');
                const main = document.querySelector('main');
                if (!h1 && !main) return null;
                const photo = document.querySelector(
                    '.pv-top-card-profile-picture, button.pv-top-card-profile-picture, img[src*="profile-displayphoto"], img[srcset*="profile-displayphoto"]'
                );
                let topEl = null;
                let n = (h1 && h1.parentElement) || (main && main.firstElementChild);
                for (let i = 0; i < 14 && n; i++) {
                    const r = n.getBoundingClientRect();
                    if (r.width >= 300 && r.height >= 70) topEl = n;
                    if (main && n === main) break;
                    n = n.parentElement;
                }
                const r = (topEl || main || h1).getBoundingClientRect();
                const photoR = photo ? photo.getBoundingClientRect() : null;
                let height = Math.min(210, Math.max(88, r.width * 0.22));
                if (photoR && photoR.top > r.top + 36) {
                    height = Math.max(72, Math.min(240, photoR.top - r.top + 8));
                }
                return {
                    x: Math.max(0, r.x),
                    y: Math.max(0, r.y),
                    width: Math.max(80, r.width),
                    height: Math.max(56, height),
                };
            }"""
        )
        if not isinstance(box, dict):
            return ""
        x = float(box.get("x") or 0)
        y = float(box.get("y") or 0)
        w = float(box.get("width") or 0)
        h = float(box.get("height") or 0)
        if w < 80 or h < 40:
            return ""
        raw = page.screenshot(
            type="jpeg",
            quality=62,
            clip={"x": x, "y": y, "width": w, "height": h},
        )
        return _jpeg_data(raw)
    except Exception:
        return ""


def _progress(cb: Any, pct: int, step: str) -> None:
    if not cb:
        return
    try:
        cb({"pct": int(pct), "step": str(step)})
    except Exception:
        return


def _capture_search_shots(page: Any, found: list[dict[str, Any]], on_progress: Any = None) -> None:
    total = max(len(found), 1)
    _wake_lazy_images(page)
    for i, item in enumerate(found):
        _progress(on_progress, 42 + int((i / total) * 48), f"Collecting photos {i + 1} of {len(found)}")
        key = item.get("key") or _card_key(item.get("url") or "")
        if key:
            loc = page.locator(f'[data-zuntra-card="{key}"]').first
            try:
                if loc.count() > 0:
                    loc.scroll_into_view_if_needed(timeout=2500)
                    page.wait_for_timeout(450)
            except Exception:
                pass
            try:
                src = page.evaluate(
                    """(k) => {
                        const img = document.querySelector('[data-zuntra-photo="' + k + '"]');
                        if (!img) return '';
                        const delayed = img.getAttribute('data-delayed-url') || img.getAttribute('data-li-src') || '';
                        const src = img.currentSrc || img.src || '';
                        const bad = (u) => !u || /^data:image\\/gif/i.test(u) || /ghost|sprite|emoji/i.test(u);
                        if (!bad(delayed)) return delayed;
                        if (!bad(src)) return src;
                        const set = (img.getAttribute('srcset') || '').split(',')[0].trim().split(' ')[0];
                        if (!bad(set)) return set;
                        return '';
                    }""",
                    key,
                )
                if src:
                    item["photo"] = str(src).strip()
            except Exception:
                pass
        photo_src = str(item.get("photo") or "").strip()
        photo = _download_image(page, photo_src) if photo_src else ""
        if not photo and key:
            try:
                img = page.locator(f'[data-zuntra-photo="{key}"]').first
                photo = _shot_locator(img, max_h=220)
            except Exception:
                photo = ""
        if photo:
            item["photo"] = photo
        elif photo_src.startswith("data:"):
            item["photo"] = photo_src
        else:
            item["photo"] = ""
        if key:
            loc = page.locator(f'[data-zuntra-card="{key}"]').first
            shot = _shot_locator(loc)
            if shot:
                item["shot"] = shot


def _peek_profiles(page: Any, found: list[dict[str, Any]], on_progress: Any = None) -> None:
    search_url = page.url
    total = max(len(found), 1)
    for i, item in enumerate(found):
        url = item.get("url")
        if not url:
            continue
        label = str(item.get("name") or "").strip() or f"profile {i + 1}"
        _progress(on_progress, 48 + int((i / total) * 46), f"Reading banner {i + 1} of {len(found)} — {label}")
        slug = unquote((str(url).split("/in/")[-1] if "/in/" in str(url) else "").split("/")[0].split("?")[0]).lower()
        covers: list[str] = []

        def on_response(response: Any) -> None:
            try:
                href = str(response.url or "")
                if not href or not response.ok:
                    return
                low = href.lower()
                if "profile-displayphoto" in low or "framedphoto" in low:
                    return
                if "licdn.com" not in low and "/dms/" not in low:
                    return
                if re.search(r"displaybackground|profile-background|backgroundimage|16aq", low, re.I):
                    covers.append(href)
            except Exception:
                return

        try:
            page.on("response", on_response)
        except Exception:
            pass
        try:
            try:
                _safe_goto(page, str(url), timeout=25000)
            except Exception:
                if not _page_matches_url(page, str(url)):
                    continue
            try:
                page.wait_for_url(re.compile(r"/in/", re.I), timeout=8000)
            except Exception:
                pass
            ready = False
            for i in range(24):
                if _header_matches(page, str(item.get("name") or ""), slug, loose=i >= 8):
                    ready = True
                    break
                page.wait_for_timeout(250)
            if not ready:
                continue
            try:
                page.evaluate("() => window.scrollTo(0, 0)")
            except Exception:
                pass
            page.wait_for_timeout(900)
            try:
                page.locator(
                    "main img, main .pv-top-card-profile-picture img, main .profile-background-image img"
                ).first.wait_for(state="visible", timeout=5000)
            except Exception:
                pass
            page.wait_for_timeout(500)
            if not _header_matches(page, str(item.get("name") or ""), slug, loose=True):
                continue
            data = page.evaluate(_HEADER_JS, slug) or {}
            _merge_text_field(item, "headline", str(data.get("headline") or ""))
            _merge_text_field(item, "location", str(data.get("location") or ""))
            company = _clean_text(str(data.get("company") or ""))
            if company:
                existing = [c for c in (item.get("companies") or []) if _clean_text(str(c))]
                if company not in existing:
                    item["companies"] = ([company] + existing)[:4]
            if not item.get("photo"):
                photo_src = str(data.get("photo") or "").strip()
                photo = _download_image(page, photo_src) if photo_src else ""
                if not photo:
                    photo = _profile_photo_shot(page)
                if photo:
                    item["photo"] = photo
            banner_src = str(data.get("banner") or "").strip()
            if not banner_src and covers:
                banner_src = covers[-1]
            banner = ""
            if banner_src and not re.search(r"profile-displayphoto", banner_src, re.I):
                banner = _download_image(page, banner_src)
            if not banner:
                banner = _profile_banner_shot(page)
            if banner:
                item["banner"] = banner
        except Exception:
            continue
        finally:
            try:
                page.remove_listener("response", on_response)
            except Exception:
                pass
    try:
        if search_url and "linkedin.com" in search_url:
            page.goto(search_url, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(800)
    except Exception:
        pass


def search_people_urls(
    name: str,
    company: str = "",
    *,
    title: str = "",
    location: str = "",
    max_profiles: int = 5,
    headless: bool = True,
    on_progress: Any = None,
) -> list[dict[str, Any]]:
    with linkedin_src_path():
        from src.auth import create_authenticated_context, open_playwright
        from src.config import get_settings

        settings = get_settings()
        settings.headless = headless
        if headless:
            settings.checkpoint_timeout_seconds = min(
                settings.checkpoint_timeout_seconds, 20
            )

        playwright = open_playwright()
        browser = None
        found: list[dict[str, Any]] = []
        seen: set[str] = set()
        try:
            _progress(on_progress, 6, "Opening LinkedIn...")
            browser, context = create_authenticated_context(playwright, settings)
            page = context.new_page()
            page.set_viewport_size({"width": 1280, "height": 900})
            _progress(on_progress, 12, "Searching people...")
            _safe_goto(page, _search_url(name, company, title, location), timeout=60000)
            _progress(on_progress, 22, "Opening People results...")
            _open_people_show_all(page)
            _ensure_global_search(page)
            page.wait_for_timeout(1200)
            try:
                page.wait_for_selector('a[href*="/in/"]', timeout=12000)
            except Exception:
                pass
            _progress(on_progress, 30, "Reading people results...")
            for _ in range(4):
                page.mouse.wheel(0, 2400)
                page.wait_for_timeout(600)
            _wake_lazy_images(page)
            page.wait_for_timeout(800)
            items = page.evaluate(_EXTRACT_JS)
            for item in items or []:
                if not isinstance(item, dict):
                    continue
                normalized = _normalize_profile_url(str(item.get("href") or ""))
                if not normalized:
                    continue
                display_name = str(item.get("name") or "").strip()
                key = normalized.lower()
                if key in seen:
                    continue
                seen.add(key)
                headline = str(item.get("headline") or "").strip()
                loc = str(item.get("location") or "").strip()
                parsed_headline, parsed_loc, companies = _from_lines(
                    list(item.get("lines") or []), display_name
                )
                if not headline:
                    headline = parsed_headline
                if not loc:
                    loc = parsed_loc
                photo_src = str(item.get("photo") or "").strip()
                found.append(
                    {
                        "url": normalized,
                        "name": display_name,
                        "key": str(item.get("key") or _card_key(normalized)),
                        "headline": headline,
                        "location": loc,
                        "photo": photo_src,
                        "banner": "",
                        "shot": "",
                        "companies": companies,
                    }
                )
            found = found[:max_profiles]
            page.wait_for_timeout(800)
            if found:
                _progress(on_progress, 42, "Collecting photos...")
                _capture_search_shots(page, found, on_progress=on_progress)
            _progress(on_progress, 96, "Finishing search...")
            page.close()
            context.close()
        except RuntimeError:
            raise
        except Exception as exc:
            if _nav_failed(exc):
                raise RuntimeError("LinkedIn took too long to load. Try again.") from None
            raise RuntimeError("LinkedIn search failed. Try again.") from None
        finally:
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass
            try:
                playwright.stop()
            except Exception:
                pass
        return found


def write_urls(path: Path, urls: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(urls) + ("\n" if urls else ""), encoding="utf-8")
