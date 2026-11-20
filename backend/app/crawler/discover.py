"""Finds candidate job links / PDFs / newspaper images on a source's listing page."""
import re
from dataclasses import dataclass
from urllib.parse import unquote, urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

from .fetch import guess_kind

POSITIVE = re.compile(
    r"(job|vacanc|career|recruit|advert|apply|application|hiring|induction|enrol|appointment|"
    r"invit|opportunit|walk[\s_-]?in|interview|openings?|\bposts?\b|"
    r"ملازمت|بھرتی|اسامی|اشتہار|نوکری|درخواست)",
    re.IGNORECASE,
)
NEGATIVE_TEXT = re.compile(
    r"(result|syllabus|answer key|merit list|roll no|admit card|date ?sheet|tender|auction|privacy|"
    r"contact|about us|sitemap|facebook|twitter|youtube|whatsapp|instagram|linkedin|annual report|"
    r"newsletter|نتیجہ|ٹینڈر)",
    re.IGNORECASE,
)
IMG_NOISE = re.compile(r"(logo|icon|sprite|avatar|favicon|arrow|bullet|button|social|flag|spacer|pixel)", re.I)

_SLD = {"gov", "org", "com", "edu", "gob", "gop", "net"}


@dataclass
class Candidate:
    url: str
    title: str
    kind: str  # 'pdf' | 'image' | 'html'
    score: int = 0


def site_key(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    labels = host.split(".")
    if len(labels) >= 3 and labels[-1] == "pk" and labels[-2] in _SLD:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def _clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _title_from_url(url: str) -> str:
    name = unquote(urlparse(url).path.rsplit("/", 1)[-1])
    name = re.sub(r"\.[a-z0-9]{2,4}$", "", name, flags=re.I)
    return _clean(re.sub(r"[-_+]+", " ", name)) or url


def extract_candidates(
    html: str, base_url: str, limit: int = 120, accept_all_media: bool = False
) -> list[Candidate]:
    soup = BeautifulSoup(html, "lxml")
    base_site = site_key(base_url)
    page_is_jobs_page = accept_all_media or bool(POSITIVE.search(unquote(urlparse(base_url).path)))
    found: dict[str, Candidate] = {}

    def add(url: str, title: str, kind: str, score: int) -> None:
        existing = found.get(url)
        if existing is None:
            found[url] = Candidate(url=url, title=title, kind=kind, score=score)
        elif len(title) > len(existing.title):
            existing.title = title
            existing.score = max(existing.score, score)

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.lower().startswith(("mailto:", "tel:", "javascript:", "#", "data:")):
            continue
        url, _ = urldefrag(urljoin(base_url, href))
        if urlparse(url).scheme not in ("http", "https"):
            continue
        if url.rstrip("/") == base_url.rstrip("/"):
            continue
        img = a.find("img")
        text = _clean(a.get_text(" ", strip=True)) or _clean(a.get("title")) or _clean(img.get("alt") if img else "")
        if NEGATIVE_TEXT.search(text):
            continue
        kind = guess_kind(url)
        haystack = f"{text} {unquote(url)}"
        score = len(POSITIVE.findall(haystack))

        if kind in ("pdf", "image"):
            if score == 0 and not page_is_jobs_page:
                continue
        else:
            if site_key(url) != base_site or score == 0:
                continue
        add(url, text or _title_from_url(url), kind, score)

    for img in soup.find_all("img", src=True):
        src = img["src"].strip()
        if src.startswith("data:"):
            continue
        url, _ = urldefrag(urljoin(base_url, src))
        if urlparse(url).scheme not in ("http", "https") or guess_kind(url) != "image":
            continue
        alt = _clean(img.get("alt") or img.get("title"))
        haystack = f"{alt} {unquote(url)}"
        if IMG_NOISE.search(haystack) or NEGATIVE_TEXT.search(alt):
            continue
        score = len(POSITIVE.findall(haystack))
        if score == 0 and not accept_all_media:
            continue
        add(url, alt or _title_from_url(url), "image", score)

    ranked = sorted(found.values(), key=lambda c: -c.score)  # stable: page order breaks ties
    return ranked[:limit]


def find_media_links(html: str, page_url: str) -> list[Candidate]:
    """PDF / ad-image links inside a job detail page (used as `ad_media_url`)."""
    out = extract_candidates(html, page_url, limit=40, accept_all_media=True)
    return [c for c in out if c.kind in ("pdf", "image")][:10]
