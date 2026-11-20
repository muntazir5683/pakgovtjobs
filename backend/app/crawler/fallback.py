"""Non-AI job parser, used when Gemini is not configured, rejected the key, or is down.

It reads the same rendered listing page the AI would, and turns every job-looking link (PDF ad, detail
page, image ad) and every vacancy-table row into one job entry. Titles come from the link / row text,
dates from the surrounding text. It is deliberately conservative: it never invents data, and rows that
mention only past years are recorded as expired. Rows it produces are tagged parse_method='fallback' and
are replaced automatically once the AI extractor later succeeds on the same ad.
"""
import re
from dataclasses import dataclass
from datetime import date, timedelta
from urllib.parse import urldefrag, urljoin

from bs4 import BeautifulSoup, Tag

from ..extractor import ExtractedJob
from ..taxonomy import normalize_education_level
from .discover import NEGATIVE_TEXT, POSITIVE, extract_candidates
from .fetch import guess_kind

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_MON = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"

_DATE_PATTERNS = [
    # 25-11-2026, 25/11/2026, 25.11.2026 (Pakistan uses day-first)
    (re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b"), "dmy"),
    # 2026-11-25
    (re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b"), "ymd"),
    # 25 Nov 2026, 25th November, 2026, 25-Nov-26
    (re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?[\s-]+{_MON}[\s-]*,?\s*(\d{{4}}|\d{{2}})\b", re.I), "dMy"),
    # Nov 25, 2026
    (re.compile(rf"\b{_MON}\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.I), "Mdy"),
]
_LAST_KW = re.compile(
    r"(last\s*date|closing\s*date|close[sd]?\b|deadline|due\s*date|last\s*day|apply\s*(?:before|by|till|until)|"
    r"submission\s*(?:date|deadline)|on\s*or\s*before|till|until|up\s*to|upto|expires?)", re.I)
_PUB_KW = re.compile(
    r"(posted|published|publish\s*date|date\s*of\s*(?:publication|advertisement)|advertis\w*\s*date|dated|issued)", re.I)

_GENERIC_LINK = re.compile(
    r"^(download|view|click\s*here|click|here|more|read\s*more|read\s*full\s*\w+|full\s*(notice|announcement|advertisement)|details?|view\s*details?|apply(\s*now|\s*online)?|"
    r"pdf|link|open|attachment|file|read|see\s*more|\.\.\.|[\W\d_]*)$", re.I)
_NAV_TITLE = re.compile(
    r"^(current\s+|latest\s+|all\s+|new\s+|open\s+|available\s+)?(jobs?|careers?|vacanc(y|ies)|openings?|"
    r"job\s+(opportunit(y|ies)|advertisements?|portal|openings?|vacancies)|recruitment|apply\s+online|"
    r"online\s+application|advertisements?|announcements?|job\s+announcements?)(\s+(here|page|list))?$", re.I)
_JUNK_TITLE = re.compile(
    r"(archive|\brules?\b|regulations?|amendments?|notifications?|guidelines?|sign\s*in|log\s*in|register|"
    r"find\s+jobs|view\s+all|edit\s+application|print|interview|syllabus|how\s+to\s+apply|job\s+description|"
    r"schedule|examination|competitive|upcoming|polic(y|ies)|\bfaqs?\b|\bfee\b|click\s+for|instructions|"
    r"download\s+(form|app)|\bforms?\b|minister|chairman|chairperson|privacy|terms|roll\s*number|\bslip\b|"
    r"extension\s+in|detail\s+of|procedure|announces|writ\s+petition|forwarding|provision\s+of|surplus|"
    r"admit|result|merit|waiting|selected|shortlist|notice\s+of|court|hearing|inaugurat|ceremony|"
    r"press\s+release|\bnews\b|seminar|workshop|tender|quotation|bid\b)", re.I)
_JOB_SIGNAL = re.compile(
    r"(advertisement\s*(no\.?|#)?\s*[\d/-]+|consolidated\s+advertisement|case\s*no|"
    r"\b(bps|bs|mp|grade)[-\s]?[ivx\d]{1,3}\b|positions?\s+vacant|vacanc|recruitment\s+(of|for|against)|"
    r"\bposts?\s+of\b|jobs?\s+(for|at|in)\b|walk[\s-]?in|"
    r"\b(officer|assistant|clerk|nurse|constable|engineer|teacher|lecturer|professor|doctor|physician|surgeon|"
    r"inspector|driver|sepoy|naib\s*qasid|chowkidar|watchman|manager|director|analyst|programmer|developer|"
    r"accountant|auditor|stenographer|typist|technician|technologist|pharmacist|dispenser|sweeper|cook|mali|"
    r"peon|orderly|operator|supervisor|coordinator|consultant|specialist|librarian|trainer|instructor|cadet|"
    r"soldier|sipahi|lineman|surveyor|draftsman|junior|senior|deputy|registrar|principal|headmaster|khalasi|"
    r"sanitary|worker|guard|nco|trade|apprentice|intern|internship)\b)", re.I)
_STRONG_SIGNAL = re.compile(r"(advertisement|advert\b|vacanc|recruit|\bposts?\b|\bbps\b|\bbs-?\d|apply|induction|hiring|jobs?\b)", re.I)
_UPLOAD_PATH_RE = re.compile(r"/(20\d{2})/(\d{1,2})/")
_KEYWORDS_RE = re.compile(r"\b(closing\s*dt|closing\s*date|closed|last\s*date|deadline)\b[:.\s]*", re.I)
_POSTS_RE = re.compile(r"\b(\d{1,5})\s*(?:posts?|vacanc(?:y|ies)|seats?|positions?)\b", re.I)
_YEAR_RE = re.compile(r"\b(20\d{2})\b")
_GRADE_RE = re.compile(r"\b(?:BPS|BS|grade)[-\s]?\d{1,2}\b", re.I)


@dataclass
class Entry:
    title: str
    url: str              # where the job lives (detail page / PDF / image) or the listing itself for table rows
    kind: str             # 'pdf' | 'image' | 'html'
    publish_date: date | None = None
    last_date: date | None = None
    total_posts: int | None = None
    from_table_row: bool = False


def _clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


# --------------------------------------------------------------------------- dates

def find_dates(text: str) -> list[tuple[int, int, date]]:
    """All (start, end, date) found in text, in order of appearance."""
    out: list[tuple[int, int, date]] = []
    for rx, fmt in _DATE_PATTERNS:
        for m in rx.finditer(text):
            try:
                if fmt == "dmy":
                    d, mo, y = int(m[1]), int(m[2]), int(m[3])
                    if mo > 12 >= d:
                        d, mo = mo, d
                elif fmt == "ymd":
                    y, mo, d = int(m[1]), int(m[2]), int(m[3])
                elif fmt == "dMy":
                    d, mo, y = int(m[1]), _MONTHS[m[2].lower()[:3]], int(m[3])
                else:
                    mo, d, y = _MONTHS[m[1].lower()[:3]], int(m[2]), int(m[3])
                if y < 100:
                    y += 2000
                if 2000 <= y <= 2100:
                    out.append((m.start(), m.end(), date(y, mo, d)))
            except (ValueError, KeyError):
                continue
    out.sort()
    dedup: list[tuple[int, int, date]] = []
    for s, e, d in out:  # drop overlapping matches of different patterns
        if not dedup or s >= dedup[-1][1]:
            dedup.append((s, e, d))
    return dedup


def classify_dates(text: str, today: date) -> tuple[date | None, date | None]:
    """Return (publish_date, last_date) using keywords first, then position / future-ness."""
    dates = find_dates(text)
    if not dates:
        return None, None
    last = pub = None
    used: set[int] = set()
    for rx, is_last in ((_LAST_KW, True), (_PUB_KW, False)):
        for kw in rx.finditer(text):
            for i, (s, _e, d) in enumerate(dates):
                if i not in used and kw.end() <= s <= kw.end() + 45:
                    used.add(i)
                    if is_last and last is None:
                        last = d
                    elif not is_last and pub is None:
                        pub = d
                    break
    rest = [d for i, (_s, _e, d) in enumerate(dates) if i not in used]
    if last is None and pub is None and rest:
        if len(rest) >= 2:
            pub, last = min(rest[:2]), max(rest[:2])
        elif rest[0] >= today:
            last = rest[0]          # a lone future date is almost always the closing date
        else:
            pub = rest[0]
    elif last is None and rest:
        later = [d for d in rest if pub is None or d >= pub]
        if later and max(later) >= today:
            last = max(later)
    elif pub is None and rest:
        earlier = [d for d in rest if d <= (last or today)]
        pub = min(earlier) if earlier else None
    if pub and last and pub > last:
        pub = None
    return pub, last


# --------------------------------------------------------------------------- titles

def _strip_dates(text: str) -> str:
    for s, e, _d in reversed(find_dates(text)):
        text = text[:s] + " " + text[e:]
    return _clean(re.sub(r"\b(last date|closing date|posted|published|dated|deadline)\b[:\s-]*", " ", text, flags=re.I))


def _strip_keywords(text: str) -> str:
    return _clean(_KEYWORDS_RE.sub(" ", text))


def _context(a: Tag) -> Tag | None:
    """The row / list item / small block that holds this link."""
    own = len(_clean(a.get_text(" ")))
    node = a.parent
    for _ in range(5):
        if node is None or node.name in ("body", "html", "table", "ul", "ol", "tbody", "section", "main"):
            return None
        text_len = len(_clean(node.get_text(" ")))
        if node.name in ("tr", "li", "article"):
            return node if text_len <= 1200 else None
        if text_len > own + 8:
            return node if text_len <= 600 else None
        node = node.parent
    return None


def _row_title(ctx: Tag) -> str:
    cells = [c for c in ctx.find_all(["td", "th", "span", "div", "p", "strong", "b", "h2", "h3", "h4", "h5"],
                                      recursive=True) if not c.find(["td", "div", "p"])] or [ctx]
    best = ""
    for c in cells:
        t = _strip_dates(_clean(c.get_text(" ")))
        if len(t) > len(best) and not _GENERIC_LINK.match(t) and not re.fullmatch(r"[\d\s./-]+", t):
            best = t
    return best


def _good_title(t: str) -> bool:
    t = _clean(re.sub(r"[\W_]+$", "", _clean(t)))
    if t.lower().startswith(("http://", "https://", "www.")):
        return False
    if len(t) < 6 or _GENERIC_LINK.match(t) or _NAV_TITLE.match(t) or NEGATIVE_TEXT.search(t):
        return False
    return bool(re.search(r"[A-Za-z\u0600-\u06FF]{3}", t))


def _tidy_title(t: str) -> str:
    t = re.sub(r"^[\W_]*(?:\d{1,3}[.)]\s+)?", "", _clean(t))
    t = re.sub(r"^(download|view|click here|apply now|read more)\s+", "", t, flags=re.I)
    return re.sub(r"[\s\-|:→»>]+$", "", t[:250]).strip(" -|:")


# --------------------------------------------------------------------------- main parser

def parse_listing(html: str, base_url: str, today: date, all_media: bool = False) -> list[Entry]:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    cands = {c.url: c for c in extract_candidates(html, base_url, limit=100000, accept_all_media=all_media)}

    entries: list[Entry] = []
    seen_titles: set[str] = set()

    def add(title: str, url: str, kind: str, ctx_text: str, row: bool = False) -> None:
        title = _tidy_title(_strip_keywords(_strip_dates(title)))
        key = title.lower()
        if not _good_title(title) or key in seen_titles or _JUNK_TITLE.search(title):
            return
        pub, last = classify_dates(ctx_text, today)
        if pub is None and last is None:
            up = _UPLOAD_PATH_RE.search(url)  # /wp-content/uploads/2022/02/file.pdf -> published 2022-02
            if up and 1 <= int(up[2]) <= 12:
                pub = date(int(up[1]), int(up[2]), 1)
        m = _POSTS_RE.search(ctx_text)
        # Accept only things that look like an actual post / advertisement, not site navigation.
        if not (_JOB_SIGNAL.search(title) or last is not None or m):
            return
        if kind == "image" and not _STRONG_SIGNAL.search(title):
            return  # photos / banners need an explicit hiring word in their alt text or file name
        years = [int(y) for y in _YEAR_RE.findall(f"{title} {ctx_text}")]
        if last is None and years and max(years) < today.year:
            last = date(max(years), 12, 31)  # only old years mentioned -> an old ad
        elif last is None and re.search(r"\bclosed\b", ctx_text, re.I):
            last = today - timedelta(days=1)  # the site itself marks it closed
        seen_titles.add(key)
        entries.append(Entry(title, url, kind, pub, last, int(m[1]) if m else None, row))

    # 1) job links (PDF / image / detail pages)
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.lower().startswith(("mailto:", "tel:", "javascript:", "#", "data:")):
            continue
        url, _ = urldefrag(urljoin(base_url, href))
        cand = cands.get(url)
        if cand is None:
            continue
        link_text = _strip_keywords(_strip_dates(_clean(a.get_text(" ", strip=True)) or _clean(a.get("title"))))
        ctx = _context(a)
        ctx_text = _clean(ctx.get_text(" ")) if ctx is not None else link_text
        title = link_text
        if not _good_title(title) and ctx is not None:
            title = _row_title(ctx)
        if not _good_title(title):
            title = cand.title if _good_title(cand.title) else ""
        if title:
            add(title, url, cand.kind, ctx_text)

    # 2) vacancy tables whose rows are not individual links
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["td"])
        if len(cells) < 2 or tr.find("a", href=True) and entries:
            continue
        row_text = _clean(tr.get_text(" "))
        if not (POSITIVE.search(row_text) or _GRADE_RE.search(row_text)):
            continue
        title = _row_title(tr)
        if title:
            add(title, base_url, guess_kind(base_url), row_text, row=True)

    return entries


def to_extracted_job(e: Entry, source: dict) -> ExtractedJob:
    level = normalize_education_level(e.title)
    return ExtractedJob(
        title=e.title,
        department=source["name"],
        sector=source["sector"],
        province=source["province"],
        education_level=None if level == "Other" else level,
        total_posts=e.total_posts,
        publish_date=e.publish_date,
        last_date=e.last_date,
        apply_url=e.url,
    )
