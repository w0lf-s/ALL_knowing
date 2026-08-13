import time
from pathlib import Path

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

from src.config import STATE_PATH, Settings, ensure_dirs

LOGIN_URL = "https://www.linkedin.com/login"
FEED_URL = "https://www.linkedin.com/feed/"


def _is_logged_in(page: Page) -> bool:
    url = page.url.lower()
    if any(part in url for part in ("/login", "/checkpoint", "/authwall", "/uas/login")):
        return False
    try:
        nav = page.locator("nav, #global-nav, [data-global-nav-id], .global-nav")
        if nav.count() > 0 and nav.first.is_visible(timeout=2000):
            return True
    except Exception:
        pass
    return any(
        part in url
        for part in (
            "linkedin.com/feed",
            "linkedin.com/in/",
            "linkedin.com/mynetwork",
            "linkedin.com/jobs",
            "linkedin.com/messaging",
        )
    )


def _dismiss_overlays(page: Page) -> None:
    selectors = [
        'button:has-text("Accept")',
        'button:has-text("Reject")',
        'button:has-text("Allow essential")',
        'button[action-type="ACCEPT"]',
        'button.artdeco-global-alert-action',
    ]
    for selector in selectors:
        try:
            btn = page.locator(selector)
            if btn.count() > 0 and btn.first.is_visible(timeout=800):
                btn.first.click(timeout=1500)
                page.wait_for_timeout(500)
        except Exception:
            continue


def _wait_for_login_success(page: Page, timeout_seconds: int) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if _is_logged_in(page):
            return True
        _dismiss_overlays(page)
        page.wait_for_timeout(2000)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=2000)
        except Exception:
            pass
    return _is_logged_in(page)


def _try_auto_fill_login(page: Page, settings: Settings) -> bool:
    email = page.locator("#username, input[name='session_key']")
    password = page.locator("#password, input[name='session_password']")
    submit = page.locator('button[type="submit"], button[data-litms-control-urn="login-submit"]')
    try:
        email.first.wait_for(state="visible", timeout=20000)
        email.first.fill(settings.linkedin_email, timeout=10000)
        password.first.fill(settings.linkedin_password, timeout=10000)
        if submit.count() > 0:
            submit.first.click(timeout=10000)
        return True
    except Exception:
        return False


def _perform_login(page: Page, settings: Settings) -> None:
    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(2000)
    _dismiss_overlays(page)
    _try_auto_fill_login(page, settings)
    page.wait_for_timeout(2000)
    if not _wait_for_login_success(page, settings.checkpoint_timeout_seconds):
        raise RuntimeError(
            "LinkedIn login did not finish in time. Keep the browser open, sign in manually "
            "(including any checkpoint/2FA), then run again."
        )


def _session_still_valid(context: BrowserContext, timeout_ms: int = 45000) -> bool:
    page = context.new_page()
    try:
        page.goto(FEED_URL, wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_timeout(1500)
        return _is_logged_in(page)
    except Exception:
        return False
    finally:
        page.close()


def create_authenticated_context(
    playwright: Playwright, settings: Settings
) -> tuple[Browser, BrowserContext]:
    ensure_dirs()
    if not settings.linkedin_email or not settings.linkedin_password:
        raise RuntimeError("LINKEDIN_EMAIL and LINKEDIN_PASSWORD must be set in .env")

    if settings.headless:
        settings.checkpoint_timeout_seconds = min(settings.checkpoint_timeout_seconds, 20)

    launch_args = {
        "headless": settings.headless,
        "slow_mo": 80 if not settings.headless else 0,
        "args": ["--disable-blink-features=AutomationControlled"],
    }
    try:
        browser = playwright.chromium.launch(channel="chrome", **launch_args)
    except Exception:
        browser = playwright.chromium.launch(**launch_args)

    state_file = Path(STATE_PATH)

    if state_file.exists():
        context = browser.new_context(
            storage_state=str(state_file),
            viewport={"width": 1280, "height": 900},
        )
        session_timeout = 20000 if settings.headless else 45000
        if _session_still_valid(context, timeout_ms=session_timeout):
            return browser, context
        context.close()

    context = browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    try:
        _perform_login(page, settings)
        context.storage_state(path=str(state_file))
    except Exception:
        try:
            page.close()
        except Exception:
            pass
        context.close()
        browser.close()
        raise
    page.close()
    return browser, context


def open_playwright() -> Playwright:
    return sync_playwright().start()
