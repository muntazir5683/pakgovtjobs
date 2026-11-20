"""HTTP + headless-browser fetching. Every function raises FetchError on failure; callers decide
whether that is fatal (listing page) or skippable (single candidate)."""
import logging
import re
import time
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

from ..config import settings

log = logging.getLogger(__name__)

PDF_EXT = (".pdf",)
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")


class FetchError(Exception):
    pass


@dataclass
class Fetched:
    url: str                # final URL after redirects
    content_type: str       # lower-cased mime without params
    body: bytes
    text: str | None = None  # decoded text for HTML


def guess_kind(url: str, content_type: str | None = None) -> str:
    """'pdf' | 'image' | 'html'"""
    ct = (content_type or "").lower()
    path = url.lower().split("?")[0].split("#")[0]
    if "pdf" in ct or path.endswith(PDF_EXT):
        return "pdf"
    if ct.startswith("image/") or path.endswith(IMAGE_EXT):
        return "image"
    return "html"


class Http:
    """Thin retrying httpx wrapper. Falls back to verify=False for the many gov sites with broken TLS."""

    def __init__(self) -> None:
        timeout = httpx.Timeout(settings.request_timeout_seconds, connect=12.0)
        headers = {
            "User-Agent": settings.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/pdf,image/*;q=0.8,*/*;q=0.5",
            "Accept-Language": "en-US,en;q=0.9,ur;q=0.7",
        }
        self._strict = httpx.Client(timeout=timeout, headers=headers, follow_redirects=True)
        self._lenient = httpx.Client(timeout=timeout, headers=headers, follow_redirects=True, verify=False)

    def close(self) -> None:
        self._strict.close()
        self._lenient.close()

    def __enter__(self) -> "Http":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _get_once(self, client: httpx.Client, url: str) -> Fetched:
        with client.stream("GET", url) as r:
            if r.status_code >= 400:
                raise FetchError(f"HTTP {r.status_code} for {url}")
            chunks, size = [], 0
            for chunk in r.iter_bytes():
                size += len(chunk)
                if size > settings.max_media_bytes:
                    raise FetchError(f"Response larger than {settings.max_media_bytes} bytes: {url}")
                chunks.append(chunk)
            body = b"".join(chunks)
            ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
            text = None
            if guess_kind(str(r.url), ctype) == "html":
                text = body.decode(r.encoding or "utf-8", errors="replace")
            return Fetched(url=str(r.url), content_type=ctype, body=body, text=text)

    def get(self, url: str, retries: int = 2) -> Fetched:
        last: Exception | None = None
        for attempt in range(retries + 1):
            for client in (self._strict, self._lenient):
                try:
                    return self._get_once(client, url)
                except FetchError as e:
                    last = e
                    break  # HTTP-level error: TLS is not the problem, go to next attempt
                except httpx.ConnectError as e:
                    last = e
                    if "CERTIFICATE" in str(e).upper() or "SSL" in str(e).upper():
                        continue  # retry same attempt with lenient client
                    break
                except (httpx.TimeoutException, httpx.TransportError) as e:
                    last = e
                    break
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
        raise FetchError(f"{type(last).__name__}: {last}" if last else f"Failed to fetch {url}")


_REVEAL_ALL_JS = """
() => {
  document.querySelectorAll('select[name$="_length"], select.dt-input').forEach(s => {
    const opts = [...s.options];
    if (opts.length) {
      const all = opts.find(o => o.value === '-1') || opts[opts.length - 1];
      s.value = all.value;
      s.dispatchEvent(new Event('change', { bubbles: true }));
    }
  });
}
"""


_ABSOLUTIZE_JS = """
() => {
  document.querySelectorAll('a[href]').forEach(a => { try { a.setAttribute('href', a.href); } catch (e) {} });
  document.querySelectorAll('img[src]').forEach(i => { try { i.setAttribute('src', i.src); } catch (e) {} });
  return document.body ? document.body.innerHTML : '';
}
"""

# Pagination controls only (never carousel arrows): DataTables, Bootstrap, WordPress, rel=next.
_NEXT_SELECTORS = [
    'a[rel="next"]',
    ".dataTables_paginate .paginate_button.next:not(.disabled)",
    ".dt-paging .dt-paging-button.next:not(.disabled)",
    ".pagination li:not(.disabled) a[rel='next']",
    ".pagination li.next:not(.disabled) a",
    '.pagination a:has-text("Next")',
    '.pagination a:has-text("›")',
    '.pagination a:has-text("»")',
    ".page-numbers.next",
    ".pager .next a",
    'nav[aria-label*="agination" i] a[aria-label*="next" i]',
]
_TAB_RE = re.compile(
    r"(current|active|open|latest|new|all|available)\s+(jobs?|openings?|vacancies|advertisements?|positions?|posts?)|"
    r"^(jobs?|vacancies|advertisements?|careers?)$", re.I)
MAX_LISTING_PAGES = 30
MAX_TABS = 8


def _collect_all_pages(page) -> str:
    """Walk 'active jobs' tabs and every pagination page of the listing; return one merged HTML document."""
    from playwright.sync_api import Error as PlaywrightError

    chunks: list[str] = []
    seen: set[int] = set()

    def snap() -> bool:
        try:
            body = page.evaluate(_ABSOLUTIZE_JS)
        except PlaywrightError:
            return False
        h = hash(body)
        if h in seen or not body:
            return False
        seen.add(h)
        chunks.append(body)
        return True

    def settle(ms: int = 700) -> None:
        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except PlaywrightError:
            pass
        page.wait_for_timeout(ms)

    snap()

    # In-page tabs such as "Current Openings" / "Active Jobs" (only ones that do not leave the page).
    try:
        tabs = page.locator('[role="tab"], .nav-tabs a, .nav-pills a, ul.tabs a, .tabs li a, .tab-link')
        for i in range(min(tabs.count(), 12)):
            if len(chunks) > MAX_TABS:
                break
            el = tabs.nth(i)
            text = " ".join((el.inner_text(timeout=1500) or "").split())
            href = el.get_attribute("href") or ""
            if not _TAB_RE.search(text) or (href and not href.startswith(("#", "javascript"))):
                continue
            el.click(timeout=3000)
            settle(600)
            snap()
    except PlaywrightError:
        pass

    for _ in range(MAX_LISTING_PAGES):
        clicked = False
        for sel in _NEXT_SELECTORS:
            try:
                loc = page.locator(sel)
                if loc.count() and loc.first.is_visible() and loc.first.is_enabled():
                    loc.first.click(timeout=4000)
                    clicked = True
                    break
            except PlaywrightError:
                continue
        if not clicked:
            break
        settle()
        try:  # a following page may itself be lazy / DataTables
            page.evaluate(_REVEAL_ALL_JS)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(400)
        except PlaywrightError:
            pass
        if not snap():
            break  # nothing new: last page (or a control that does nothing)

    if len(chunks) <= 1:
        return page.content()
    return "<html><body>" + "\n".join(chunks) + "</body></html>"


def render_html(url: str, paginate: bool = False) -> str:
    """Render a JS-heavy page with Playwright (sync API; runs fine inside a worker thread).
    With paginate=True it also walks 'active jobs' tabs and all pagination pages."""
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as e:  # pragma: no cover
        raise FetchError("playwright is not installed") from e

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True, args=[
                    "--disable-blink-features=AutomationControlled",
                    "--ignore-certificate-errors",
                    "--disable-dev-shm-usage",  # containers have a tiny /dev/shm
                ],
            )
            try:
                ctx = browser.new_context(
                    user_agent=settings.user_agent,
                    ignore_https_errors=True,
                    locale="en-US",
                    viewport={"width": 1366, "height": 850},
                    extra_http_headers={"Accept-Language": "en-US,en;q=0.9,ur;q=0.7"},
                )
                ctx.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
                page = ctx.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=settings.playwright_timeout_ms)
                try:
                    page.wait_for_load_state("networkidle", timeout=10000)
                except PlaywrightError:
                    pass  # chatty pages never go idle; use what has rendered
                try:
                    # Reveal everything: show all rows of DataTables-style tables, then scroll to
                    # trigger lazy-loaded lists.
                    page.evaluate(_REVEAL_ALL_JS)
                    for _ in range(4):
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        page.wait_for_timeout(500)
                    page.wait_for_timeout(800)
                except PlaywrightError:
                    pass
                if not paginate:
                    return page.content()
                return _collect_all_pages(page)
            finally:
                browser.close()
    except PlaywrightError as e:
        raise FetchError(f"Playwright: {str(e).splitlines()[0]}") from e


_BLOCK_RE = re.compile(
    r"(has been blocked|web page blocked|access denied|attack id|request blocked|you have been blocked|"
    r"are you a robot|verify you are human|captcha|just a moment|page not available|service unavailable|"
    r"temporarily unavailable|under maintenance)",
    re.IGNORECASE,
)


def looks_blocked(text: str) -> str | None:
    """Detect firewall / error pages that come back with HTTP 200. Returns a short reason or None.
    Only short pages qualify, so a real page that merely mentions 'captcha' is never flagged."""
    if len(text) > 1200:
        return None
    m = _BLOCK_RE.search(text)
    return " ".join(text.split())[:100] if m else None


def html_to_text(html: str, limit: int = 150000) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "svg", "iframe", "header", "footer", "nav"]):
        tag.decompose()
    text = soup.get_text("\n")
    lines = [ln.strip() for ln in text.splitlines()]
    out = "\n".join(ln for ln in lines if ln)
    return out[:limit]
