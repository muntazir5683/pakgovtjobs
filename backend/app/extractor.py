"""Gemini Flash extraction: HTML text, PDFs and newspaper-clipping images -> normalized job records."""
import base64
import json
import logging
import threading
import time
from datetime import date

import httpx
from pydantic import BaseModel, ValidationError, field_validator

from .config import settings
from .taxonomy import (
    EDUCATION_LEVELS,
    PROVINCES,
    SECTORS,
    normalize_education_level,
    normalize_province,
    normalize_sector,
)

log = logging.getLogger(__name__)

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class ExtractionError(Exception):
    """Transient or unknown failure - the candidate should be retried on the next crawl."""


class UnsupportedContent(Exception):
    """Permanent failure for this input (blocked, empty, unreadable) - do not retry."""


class ExtractedJob(BaseModel):
    title: str
    department: str | None = None
    sector: str | None = None
    province: str | None = None
    education: str | None = None
    education_level: str | None = None
    total_posts: int | None = None
    publish_date: date | None = None
    last_date: date | None = None
    apply_url: str | None = None

    @field_validator("publish_date", "last_date", mode="before")
    @classmethod
    def _lenient_date(cls, v):
        if not v:
            return None
        try:
            return date.fromisoformat(str(v).strip()[:10])
        except ValueError:
            return None

    @field_validator("total_posts", mode="before")
    @classmethod
    def _lenient_int(cls, v):
        if v is None or v == "":
            return None
        try:
            n = int(v)
        except (TypeError, ValueError):
            return None
        return n if n > 0 else None

    def normalized(self) -> "ExtractedJob":
        self.title = " ".join(self.title.split())[:300]
        self.sector = normalize_sector(self.sector)
        self.province = normalize_province(self.province)
        self.education_level = normalize_education_level(self.education_level or self.education)
        return self


SYSTEM_PROMPT = """You extract government job advertisements from Pakistan.
The input is a web page's text, a PDF, or a scanned newspaper clipping (English and/or Urdu).

Rules:
- Set is_job_ad=true only if the input announces at least one real, open recruitment / vacancy / induction.
  Results, admit cards, syllabi, tenders, merit lists, news and policy documents are NOT job ads.
- Return ONE ENTRY IN `jobs` FOR EVERY INDIVIDUAL POST. Never group several posts into one listing.
  A consolidated advertisement (e.g. FPSC / PPSC / SPSC / KPPSC with dozens of posts), a table of vacancies,
  or a list of departments must be expanded: one job per post / per table row / per advertisement number,
  each with its own total_posts, education, department and last_date when those differ.
  Do not skip any row, even if there are 100+. Continue until every post in the input is listed.
- `title` must be specific and unique within the input: the post name plus its BPS/BS grade and, when the same
  post name appears for several departments or case numbers, the department or case no. appended
  (e.g. "Assistant (BS-16) - Ministry of Finance", "Charge Nurse Female (BS-16) - Case No. 33D2026").
- Write every field in English (translate / transliterate Urdu). Never invent values: use null when the
  input does not state them.
- last_date and publish_date are ISO YYYY-MM-DD. last_date is the final day to apply. Resolve partial dates
  ("25 Nov", "25-11") using the year that makes sense relative to today's date given below.
- total_posts is the total number of vacancies as an integer (sum them if several are given).
- apply_url: the official online application / portal link ONLY if it is explicitly present in the input; else null.
- sector: one of __SECTORS__. Use "Banking & Finance" for banks, microfinance and financial institutions
  (SBP, NBP, BOP, HBL, ...); "Development & Societies" for development authorities (CDA, LDA, RDA, ...) and
  housing societies / real-estate developers (DHA, Bahria Town, ...); "Testing" for testing-agency notices
  (NTS, OTS, PTS, ...); otherwise the government body's own sector.
- province: one of the allowed values; use "All Pakistan" for nationwide, "Islamabad" for federal-capital posts.
- education: the minimum qualification as written in the ad, short (e.g. "BS Computer Science (16 years)").
- education_level: the closest single level from the allowed list.
"""


SYSTEM_PROMPT = SYSTEM_PROMPT.replace("__SECTORS__", ", ".join(SECTORS))


def _response_schema() -> dict:
    job = {
        "type": "OBJECT",
        "properties": {
            "title": {"type": "STRING"},
            "department": {"type": "STRING", "nullable": True},
            "sector": {"type": "STRING", "enum": SECTORS},
            "province": {"type": "STRING", "enum": PROVINCES},
            "education": {"type": "STRING", "nullable": True},
            "education_level": {"type": "STRING", "enum": EDUCATION_LEVELS},
            "total_posts": {"type": "INTEGER", "nullable": True},
            "publish_date": {"type": "STRING", "nullable": True},
            "last_date": {"type": "STRING", "nullable": True},
            "apply_url": {"type": "STRING", "nullable": True},
        },
        "required": ["title", "sector", "province", "education_level"],
    }
    return {
        "type": "OBJECT",
        "properties": {
            "is_job_ad": {"type": "BOOLEAN"},
            "jobs": {"type": "ARRAY", "items": job},
        },
        "required": ["is_job_ad", "jobs"],
    }


_rate_lock = threading.Lock()
_last_call = 0.0


def _throttle() -> None:
    global _last_call
    with _rate_lock:
        wait = settings.gemini_min_interval_seconds - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()


def text_part(text: str) -> dict:
    return {"text": text}


def media_part(body: bytes, mime: str) -> dict:
    return {"inline_data": {"mime_type": mime, "data": base64.b64encode(body).decode()}}


def api_key_configured() -> bool:
    key = settings.gemini_api_key.strip()
    return bool(key) and not key.upper().startswith("PASTE_")


def _post_model(model: str, payload: dict, key: str, attempts: int) -> dict:
    url = API_URL.format(model=model)
    headers = {"x-goog-api-key": key, "Content-Type": "application/json"}
    last: str = ""
    for attempt in range(attempts):
        _throttle()
        try:
            r = httpx.post(url, headers=headers, json=payload, timeout=120)
        except httpx.HTTPError as e:
            last = f"{type(e).__name__}: {e}"
        else:
            if r.status_code == 200:
                return r.json()
            last = f"HTTP {r.status_code}: {r.text[:300]}"
            if r.status_code == 400:
                if "API_KEY_INVALID" in r.text or "API key not valid" in r.text:
                    raise ExtractionError("Gemini auth failed (400: API key not valid); check GEMINI_API_KEY")
                raise UnsupportedContent(last)
            if r.status_code in (401, 403):
                raise ExtractionError(f"Gemini auth failed ({r.status_code}); check GEMINI_API_KEY")
            if r.status_code == 404:
                break  # model name not available for this key: no point retrying it
        if attempt < attempts - 1:
            time.sleep(3 * (2**attempt))  # 3s, 6s, 12s - covers 429 / 5xx
    raise ExtractionError(f"Gemini request failed ({model}): {last}")


def _post(payload: dict) -> dict:
    key = settings.gemini_api_key.strip()
    if not api_key_configured():
        raise ExtractionError("GEMINI_API_KEY is not configured")
    fallback = settings.gemini_fallback_model.strip()
    has_fallback = bool(fallback) and fallback != settings.gemini_model
    try:
        return _post_model(settings.gemini_model, payload, key, attempts=3 if has_fallback else 4)
    except ExtractionError as e:
        if not has_fallback or "auth failed" in str(e):
            raise
        log.warning("%s - retrying once with fallback model %s", e, fallback)
        alt = json.loads(json.dumps(payload))  # deep copy; 2.0 models reject thinkingConfig
        alt["generationConfig"].pop("thinkingConfig", None)
        return _post_model(fallback, alt, key, attempts=2)


def _salvage_truncated(raw: str) -> dict | None:
    start = raw.find('"jobs"')
    start = raw.find("[", start) if start != -1 else -1
    if start == -1:
        return None
    dec, i, jobs = json.JSONDecoder(), start + 1, []
    while True:
        while i < len(raw) and raw[i] in " \n\r\t,":
            i += 1
        if i >= len(raw) or raw[i] != "{":
            break
        try:
            item, i = dec.raw_decode(raw, i)
        except json.JSONDecodeError:
            break
        jobs.append(item)
    return {"is_job_ad": bool(jobs), "jobs": jobs} if jobs else None


def extract_jobs(parts: list[dict], today: date, hint: str = "") -> list[ExtractedJob]:
    """Send `parts` (text and/or inline media) to Gemini and return validated jobs (maybe empty)."""
    prompt = f"Today's date (Asia/Karachi): {today.isoformat()}.\n{hint}\nExtract the job ad(s) from the input below."
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}, *parts]}],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 65536,  # consolidated ads can contain 100+ posts
            "responseMimeType": "application/json",
            "responseSchema": _response_schema(),
        },
    }
    if "2.5" in settings.gemini_model:
        # Extraction does not need "thinking"; disabling it leaves the whole budget for the post list.
        payload["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 0}
    data = _post(payload)

    candidates = data.get("candidates") or []
    if not candidates:
        reason = (data.get("promptFeedback") or {}).get("blockReason", "no candidates")
        raise UnsupportedContent(f"Gemini returned nothing ({reason})")
    content_parts = (candidates[0].get("content") or {}).get("parts") or []
    raw = "".join(p.get("text", "") for p in content_parts).strip()
    if not raw:
        raise UnsupportedContent(f"Empty Gemini response (finishReason={candidates[0].get('finishReason')})")
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as e:
        obj = _salvage_truncated(raw)  # output cut off mid-list: keep every complete job before the cut
        if obj is None:
            raise ExtractionError(f"Gemini returned invalid JSON: {e}") from e
        log.warning("Gemini output truncated; salvaged %s job(s)", len(obj["jobs"]))

    if not obj.get("is_job_ad"):
        return []
    jobs: list[ExtractedJob] = []
    for item in obj.get("jobs") or []:
        try:
            jobs.append(ExtractedJob.model_validate(item).normalized())
        except ValidationError as e:
            log.warning("Dropping malformed extracted job: %s", e.errors()[:1])
    return jobs
