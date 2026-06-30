import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from features.macro_narrative import (
    MacroNarrativeFeatures,
    load_narrative_json,
    neutral_narrative,
    save_narrative_json,
)

logger = logging.getLogger("quorrin.fxstreet_fetcher")

FXSTREET_URL = "https://www.fxstreet.com/analysis"
NARRATIVE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "live",
)
NARRATIVE_PENDING = os.path.join(NARRATIVE_DIR, "narrative_pending.json")
NARRATIVE_ACTIVE = os.path.join(NARRATIVE_DIR, "narrative_active.json")
NARRATIVE_ERROR = os.path.join(NARRATIVE_DIR, "narrative_error.json")
LLM_SYSTEM_PROMPT = (
    "You are a macro analyst. Extract structured data from this FX market commentary. "
    "Return ONLY valid JSON matching this exact schema:\n"
    '{\n  "usd_strength_narrative": 0.0-1.0,\n  "geopol_risk_score": 0.0-1.0,\n'
    '  "fed_hawkishness": 0.0-1.0,\n  "rbnz_hawkishness": 0.0-1.0,\n'
    '  "rba_hawkishness": 0.0-1.0,\n  "boj_intervention_risk": 0.0-1.0,\n'
    '  "energy_crisis_pressure": 0.0-1.0,\n  "usd_bias": "bullish"|"bearish"|"neutral",\n'
    '  "nzd_bias": "bullish"|"bearish"|"neutral",\n'
    '  "aud_bias": "bullish"|"bearish"|"neutral",\n'
    '  "jpy_bias": "bullish"|"bearish"|"neutral",\n'
    '  "cad_bias": "bullish"|"bearish"|"neutral",\n'
    '  "eur_bias": "bullish"|"bearish"|"neutral",\n'
    '  "key_events": ["event1", "event2"],\n'
    '  "overall_regime": "risk_on"|"risk_off"|"data_driven"|"geopol_tension",\n'
    '  "confidence": 0.0-1.0\n}'
)


def fetch_fxstreet_article() -> str | None:
    url = FXSTREET_URL
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Strategy 1: find article link containing both "weekly" and "forecast"
        candidates = []
        for a in soup.find_all("a", href=True):
            txt = a.get_text(strip=True)
            if "weekly" in txt.lower() and "forecast" in txt.lower():
                candidates.append(a)
        if candidates:
            link = candidates[0]
            href = link["href"]
            if href.startswith("/"):
                href = "https://www.fxstreet.com" + href
            try:
                article_resp = requests.get(href, headers=headers, timeout=15)
                article_resp.raise_for_status()
                article_soup = BeautifulSoup(article_resp.text, "html.parser")
                # Strategy 1a: extract from the main article wrapper (Tailwind redesign)
                wrap = article_soup.find("div", class_=re.compile(r"overflow-clip"))
                if wrap:
                    for tag in wrap.find_all(["script", "style", "nav", "footer"]):
                        tag.decompose()
                    for tag in wrap.find_all("div", class_=re.compile(r"hidden|text-body-xs|text-neutral-")):
                        tag.decompose()
                    text = wrap.get_text(separator="\n", strip=True)
                    if len(text) > 200:
                        return text
                # Strategy 1b: fallback to old content classes
                body = article_soup.find(
                    "div", class_=re.compile(r"article-content|entry-content|post-content|fxs_contentView")
                )
                if body:
                    for tag in body.find_all(["script", "style", "nav", "footer"]):
                        tag.decompose()
                    text = body.get_text(separator="\n", strip=True)
                    if len(text) > 200:
                        return text
            except (requests.exceptions.RequestException, OSError):
                pass

        # Strategy 2: concatenate article preview snippets from the listing page
        parts = []
        for div in soup.find_all("div", class_=re.compile(r"text-body-md")):
            text = div.get_text(separator="\n", strip=True)
            if text and len(text) > 50:
                parts.append(text)
        if parts:
            combined = "\n\n".join(parts)
            logger.info("FXStreet: using %d listing snippets (%d chars)", len(parts), len(combined))
            return combined

        return None
    except (requests.exceptions.RequestException, OSError, ValueError) as e:
        logger.error("Failed to fetch FXStreet: %s", e)
        return None


def call_llm(text: str, api_key: str, model: str = "deepseek-v4-flash-free", retries: int = 2) -> dict | None:
    url = "https://opencode.ai/zen/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "content-type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": 4096,
        "reasoning_effort": "low",
        "messages": [
            {"role": "system", "content": LLM_SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
    }
    for attempt in range(retries + 1):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=60)
            resp.raise_for_status()
            body = resp.json()
            content = body.get("choices", [{}])[0].get("message", {}).get("content", "")
            json_match = re.search(r"\{.*\}", content, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            logger.warning("LLM attempt %d: no JSON in response (len=%d)", attempt + 1, len(content))
        except (requests.exceptions.RequestException, OSError, ValueError, KeyError) as e:
            logger.warning("LLM attempt %d failed: %s", attempt + 1, e)
        if attempt < retries:
            time.sleep(2**attempt)
    logger.error("LLM call failed after %d attempts", retries + 1)
    return None


def run_weekly_narrative_pipeline(api_key: str | None = None) -> bool:
    os.makedirs(NARRATIVE_DIR, exist_ok=True)
    text = fetch_fxstreet_article()
    if not text:
        _write_error("scrape_failed", "No FXStreet article found or fetch returned empty")
        logger.warning("FXStreet scrape returned no content — narrative not updated")
        return False

    content_hash = hashlib.sha256(text.encode()).hexdigest()[:12]
    week_start = datetime.now().strftime("%Y-%m-%d")

    if api_key:
        llm_result = call_llm(text, api_key)
        if llm_result is None:
            _write_error("llm_failed", "LLM call returned no result — using neutral fallback")
            logger.warning("LLM extraction failed — falling back to neutral narrative")
            features = neutral_narrative(week_start)
            features.narrative_version = f"{week_start}_{content_hash}_fallback"
        else:
            llm_result["narrative_version"] = f"{week_start}_{content_hash}"
            features = MacroNarrativeFeatures(
                week_start=week_start,
                **{k: v for k, v in llm_result.items() if k in MacroNarrativeFeatures.__dataclass_fields__},
            )
    else:
        logger.info("No API key set — writing neutral fallback narrative for %s", week_start)
        features = neutral_narrative(week_start)
        features.narrative_version = f"{week_start}_{content_hash}_fallback"

    save_narrative_json(NARRATIVE_PENDING, features)
    logger.info("Narrative pending for week starting %s (version=%s)", week_start, features.narrative_version)
    return True


def confirm_pending_narrative() -> bool:
    if not os.path.exists(NARRATIVE_PENDING):
        logger.warning("No pending narrative to confirm")
        return False
    try:
        import shutil

        shutil.copy2(NARRATIVE_PENDING, NARRATIVE_ACTIVE)
        logger.info("Narrative confirmed: %s → %s", NARRATIVE_PENDING, NARRATIVE_ACTIVE)
        if os.path.exists(NARRATIVE_ERROR):
            os.remove(NARRATIVE_ERROR)
        return True
    except (OSError, shutil.Error) as e:
        logger.error("Failed to confirm narrative: %s", e)
        return False


def get_active_narrative() -> MacroNarrativeFeatures | None:
    if not os.path.exists(NARRATIVE_ACTIVE):
        return None
    try:
        return load_narrative_json(NARRATIVE_ACTIVE)
    except (OSError, ValueError) as e:
        logger.error("Failed to load active narrative: %s", e)
        return None


def get_pending_narrative() -> MacroNarrativeFeatures | None:
    if not os.path.exists(NARRATIVE_PENDING):
        return None
    try:
        return load_narrative_json(NARRATIVE_PENDING)
    except (OSError, ValueError) as e:
        logger.warning("Failed to load pending narrative: %s", e)
        return None


def is_narrative_stale(week_start: str) -> bool:
    try:
        start = datetime.strptime(week_start, "%Y-%m-%d").date()
        now = datetime.now().date()
        days_since = (now - start).days
        return days_since >= 7
    except (ValueError, TypeError):
        return True


def _write_error(reason: str, detail: str) -> None:
    try:
        with open(NARRATIVE_ERROR, "w") as f:
            json.dump({"reason": reason, "detail": detail, "timestamp": datetime.now().isoformat()}, f)
    except OSError:
        pass


def get_fetch_error() -> dict | None:
    if not os.path.exists(NARRATIVE_ERROR):
        return None
    try:
        with open(NARRATIVE_ERROR) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def get_narrative_status() -> dict:
    active = get_active_narrative()
    pending = get_pending_narrative()
    error = get_fetch_error()
    stale = active is None or is_narrative_stale(active.week_start)
    week_start_candidates = [p.week_start for p in [pending, active] if p]
    return {
        "week_start": max(week_start_candidates) if week_start_candidates else datetime.now().strftime("%Y-%m-%d"),
        "active": active.to_dict() if active else None,
        "pending": pending.to_dict() if pending else None,
        "stale": stale,
        "fetch_error": error,
        "has_pending": pending is not None,
        "needs_confirmation": pending is not None and (active is None or pending.week_start != active.week_start),
    }
