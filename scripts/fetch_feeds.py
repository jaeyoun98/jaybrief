"""Fetch RSS/Atom sources, classify by theme, dedup, write data/feed.json.

Run from anywhere; paths are resolved relative to the repo root.
Writes the output only when the item set actually changed, so the
calling workflow can use `git diff` to decide whether to commit.
"""

import hashlib
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import feedparser
import requests

ROOT = Path(__file__).resolve().parents[1]
SOURCES_PATH = ROOT / "sources.json"
OUT_PATH = ROOT / "data" / "feed.json"

UA = "Mozilla/5.0 (compatible; JayBrief/1.0)"
TIMEOUT = 20
WINDOW_HOURS = 72
MAX_ITEMS = 800
SNIPPET_MAX = 280

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
NORM_RE = re.compile(r"[^0-9a-z가-힣]+")


def now_utc():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def feed_url(src):
    gn = src.get("google_news")
    if not gn:
        return src["feed"]
    params = {"q": gn["q"], "hl": gn["hl"], "gl": gn["gl"], "ceid": gn["ceid"]}
    return "https://news.google.com/rss/search?" + urlencode(params)


def clean_text(raw):
    if not raw:
        return ""
    import html as htmllib

    text = htmllib.unescape(TAG_RE.sub(" ", raw))
    return WS_RE.sub(" ", text).strip()


def normalize_title(title):
    return NORM_RE.sub("", title.lower())


def item_id(title):
    return hashlib.sha1(normalize_title(title).encode("utf-8")).hexdigest()[:16]


def parse_published(entry):
    for attr in ("published_parsed", "updated_parsed"):
        parsed = entry.get(attr)
        if parsed:
            try:
                return datetime.fromtimestamp(time.mktime(parsed), tz=timezone.utc)
            except (OverflowError, ValueError):
                continue
    return None


def compile_rules(keyword_rules):
    """Latin keywords match on word boundaries, Korean ones as substrings."""
    compiled = {}
    for theme, keywords in keyword_rules.items():
        patterns = []
        for kw in keywords:
            if re.fullmatch(r"[\x00-\x7f]+", kw):
                patterns.append(re.compile(r"\b" + re.escape(kw) + r"\b"))
            else:
                patterns.append(re.compile(re.escape(kw)))
        compiled[theme] = patterns
    return compiled


def classify(text, compiled_rules):
    lowered = text.lower()
    return [t for t, pats in compiled_rules.items() if any(p.search(lowered) for p in pats)]


def strip_gn_publisher(title):
    """Google News titles end with ' - Publisher'."""
    return re.sub(r"\s+-\s+[^-]+$", "", title).strip()


def collect(source, compiled_rules):
    resp = requests.get(feed_url(source), headers={"User-Agent": UA}, timeout=TIMEOUT)
    resp.raise_for_status()
    parsed = feedparser.parse(resp.content)
    is_gn = bool(source.get("google_news"))
    items = []
    for entry in parsed.entries:
        title = clean_text(entry.get("title", ""))
        url = entry.get("link", "")
        if not title or not url:
            continue
        source_name = source["name"]
        if is_gn:
            gn_src = entry.get("source", {}).get("title")
            if gn_src:
                source_name = gn_src
            title = strip_gn_publisher(title) or title
        snippet = "" if is_gn else clean_text(entry.get("summary", ""))[:SNIPPET_MAX]

        if source.get("classify"):
            themes = classify(f"{title} {snippet}", compiled_rules)
            if not themes:
                themes = source.get("fallback_themes", [])
            if not themes:
                continue
        else:
            themes = source["themes"]

        items.append(
            {
                "id": item_id(title),
                "title": title,
                "url": url,
                "source": source_name,
                "source_id": source["id"],
                "themes": themes,
                "published": iso(parse_published(entry) or now_utc()),
                "lang": source["lang"],
                "snippet": snippet,
            }
        )
    return items


def main():
    config = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
    compiled_rules = compile_rules(config["keyword_rules"])

    old_items = []
    if OUT_PATH.exists():
        old_items = json.loads(OUT_PATH.read_text(encoding="utf-8")).get("items", [])
    merged = {item["id"]: item for item in old_items}

    failures = []
    for source in config["sources"]:
        try:
            fetched = collect(source, compiled_rules)
        except Exception as exc:  # per-source isolation: one bad feed never kills the run
            failures.append(f"{source['id']}: {exc}")
            continue
        fresh = 0
        for item in fetched:
            if item["id"] not in merged:  # keep first-seen version to minimize churn
                merged[item["id"]] = item
                fresh += 1
        print(f"{source['id']}: {len(fetched)} items, {fresh} new")

    if failures:
        print("failed sources:\n  " + "\n  ".join(failures), file=sys.stderr)
    if len(failures) == len(config["sources"]):
        print("all sources failed, aborting", file=sys.stderr)
        return 1

    cutoff = iso(now_utc() - timedelta(hours=WINDOW_HOURS))
    items = [i for i in merged.values() if i["published"] >= cutoff]
    items.sort(key=lambda i: i["published"], reverse=True)
    items = items[:MAX_ITEMS]

    if [i["id"] for i in items] == [i["id"] for i in old_items]:
        print(f"no change ({len(items)} items in window)")
        return 0

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"generated_at": iso(now_utc()), "items": items}
    OUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(f"wrote {len(items)} items ({len(items) - len(old_items):+d})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
