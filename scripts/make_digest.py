"""Summarize recent feed items per theme via Gemini and write data/digest.json.

Requires GEMINI_API_KEY in the environment (free-tier key works).
Exits 0 with a notice when the key is missing so the scheduled workflow
stays green before the secret is configured.
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
FEED_PATH = ROOT / "data" / "feed.json"
OUT_PATH = ROOT / "data" / "digest.json"
ARCHIVE_DIR = ROOT / "data" / "digests"

KST = timezone(timedelta(hours=9))
MAX_LOOKBACK_HOURS = 30  # hard cap even if the previous digest is older
OVERLAP_MINUTES = 30     # re-cover a little of the previous window so nothing falls in a gap
MAX_PER_THEME = 120
RETRIES = 3

EDITION_SLOTS = [  # (kst_hour_lower_bound, slot name); scheduled runs: 07:30/12:30/18:30/21:00
    (20, "night"),
    (15, "evening"),
    (10, "noon"),
    (0, "morning"),
]

PROMPT_TEMPLATE = """당신은 반도체·소프트웨어 테크 섹터 전문 투자 뉴스 에디터입니다.
아래는 최근 {hours}시간 동안 수집된 뉴스 헤드라인입니다. 각 줄은 `[기사ID] (매체) 제목 — 요약` 형식입니다.

테마별로 투자자 관점의 브리핑을 작성하세요:
- 같은 사건을 다룬 여러 기사는 하나의 story로 묶습니다.
- 주가·실적·수급·경쟁구도에 영향을 주는 뉴스를 우선하고, 단순 제품 홍보나 보도자료성 기사는 제외합니다.
- story마다 근거가 된 기사ID를 article_ids에 넣습니다 (주어진 ID만 사용).
- headline은 한 줄 요지, body는 2~4문장으로 맥락과 투자 시사점까지.
- importance: 1(참고) ~ 3(중요).
- 전부 한국어로 작성하되 기술용어·고유명사는 영어 원문을 유지합니다.

다음 JSON schema로만 응답하세요:
{{"themes": [{{"theme": "semi|sw", "overview": "테마 전체 흐름 2~3문장", "stories": [{{"headline": "...", "body": "...", "article_ids": ["..."], "importance": 1}}]}}]}}

## 반도체 (theme: semi)
{semi_lines}

## SW테크 (theme: sw)
{sw_lines}
"""


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def recent_lines(items, theme, cutoff):
    lines = []
    for item in items:
        if theme in item["themes"] and item["published"] >= cutoff:
            snippet = f" — {item['snippet'][:160]}" if item.get("snippet") else ""
            lines.append(f"[{item['id']}] ({item['source']}) {item['title']}{snippet}")
        if len(lines) >= MAX_PER_THEME:
            break
    return lines


def call_gemini(api_key, model, prompt):
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "response_mime_type": "application/json",
            "temperature": 0.3,
            "maxOutputTokens": 8192,
        },
    }
    last_error = None
    for attempt in range(1, RETRIES + 1):
        try:
            resp = requests.post(url, json=body, timeout=120)
        except requests.RequestException as exc:
            last_error = exc
            resp = None
        if resp is not None and resp.status_code not in (429, 500, 503):
            resp.raise_for_status()
            data = resp.json()
            try:
                return data["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError, TypeError):
                # empty candidates (safety block) or content without parts
                raise RuntimeError(f"unexpected Gemini response: {json.dumps(data)[:500]}")
        if attempt < RETRIES:
            wait = 30 * attempt
            reason = f"HTTP {resp.status_code}" if resp is not None else repr(last_error)
            print(f"{reason}, retrying in {wait}s ({attempt}/{RETRIES})")
            time.sleep(wait)
    if resp is not None:
        resp.raise_for_status()
    raise RuntimeError(f"Gemini request failed after {RETRIES} attempts: {last_error!r}")


def main():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY not set - skipping digest (add the repo secret to enable)")
        return 0
    model = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")

    if not FEED_PATH.exists():
        print("data/feed.json missing - skipping digest (run fetch_feeds.py first)")
        return 0
    items = json.loads(FEED_PATH.read_text(encoding="utf-8"))["items"]
    now = datetime.now(timezone.utc)

    # summarize only what arrived since the previous digest (plus a small overlap),
    # so the four daily editions don't keep re-covering the same stories
    cutoff = iso(now - timedelta(hours=MAX_LOOKBACK_HOURS))
    if OUT_PATH.exists():
        try:
            prev_gen = json.loads(OUT_PATH.read_text(encoding="utf-8"))["generated_at"]
            prev_dt = datetime.strptime(prev_gen, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            cutoff = max(cutoff, iso(prev_dt - timedelta(minutes=OVERLAP_MINUTES)))
        except (ValueError, KeyError, json.JSONDecodeError):
            pass  # unreadable previous digest -> fall back to the max lookback
    semi_lines = recent_lines(items, "semi", cutoff)
    sw_lines = recent_lines(items, "sw", cutoff)
    if not semi_lines and not sw_lines:
        print("no recent items to summarize, skipping")
        return 0

    window_hours = max(1, round((now - datetime.strptime(cutoff, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)).total_seconds() / 3600))
    prompt = PROMPT_TEMPLATE.format(
        hours=window_hours,
        semi_lines="\n".join(semi_lines) or "(기사 없음)",
        sw_lines="\n".join(sw_lines) or "(기사 없음)",
    )
    print(f"summarizing {len(semi_lines)} semi + {len(sw_lines)} sw items with {model}")

    raw = call_gemini(api_key, model, prompt).strip()
    if raw.startswith("```"):  # JSON mode occasionally still fences the output
        raw = re.sub(r"^```[a-z]*\s*|\s*```$", "", raw)
    parsed = json.loads(raw)
    themes = parsed if isinstance(parsed, list) else parsed["themes"]

    valid_ids = {item["id"] for item in items}
    for theme in themes:
        for story in theme.get("stories", []):
            story["article_ids"] = [i for i in story.get("article_ids", []) if i in valid_ids]

    now_kst = now.astimezone(KST)
    edition = next(slot for bound, slot in EDITION_SLOTS if now_kst.hour >= bound)
    digest = {
        "generated_at": iso(now),
        "date": now_kst.strftime("%Y-%m-%d"),
        "edition": edition,
        "model": model,
        "themes": themes,
    }
    payload = json.dumps(digest, ensure_ascii=False, indent=1) + "\n"
    OUT_PATH.write_text(payload, encoding="utf-8")
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    archive = ARCHIVE_DIR / f"{digest['date']}-{digest['edition']}.json"
    archive.write_text(payload, encoding="utf-8")
    print(f"wrote digest ({sum(len(t.get('stories', [])) for t in themes)} stories) -> {archive.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
