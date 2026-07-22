"""Fetch RSS/Atom sources, classify by theme, dedup, write data/feed.json.

Run from anywhere; paths are resolved relative to the repo root.
Writes the output only when the normalized item payload actually changed, so the
calling workflow can use `git diff` to decide whether to commit.

Each item is also enriched with `cluster_id` (near-duplicate story grouping via
title-shingle Jaccard), `company_ids` (watchlist matches from companies.json),
and `score` (tier-weighted distinct-outlet count plus watchlist bonus). All
three are recomputed every run as a pure function of the selected item set and
config, so identical inputs produce identical output. Titles in different
languages never share shingles, so ko/en copies of one story stay separate
clusters (known limitation).
"""

import calendar
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import feedparser
import requests

ROOT = Path(__file__).resolve().parents[1]
SOURCES_PATH = ROOT / "sources.json"
COMPANIES_PATH = ROOT / "companies.json"
OUT_PATH = ROOT / "data" / "feed.json"

UA = "Mozilla/5.0 (compatible; JayBrief/1.0)"
TIMEOUT = 20
WINDOW_HOURS = 72
MAX_ITEMS = 800
GN_PER_SOURCE_MAX = 60
GN_POOL_MAX = 240
SNIPPET_MAX = 280

# Keep weights dyadic (x.0/x.5): float sums stay exact and order-independent.
TIER_WEIGHTS = {1: 3.0, 2: 2.0, 3: 1.0}
DEFAULT_TIER = 3  # stored items can outlive their source's removal from sources.json
WATCHLIST_BONUS = 1.0
# 0.45 calibrated on live data (2026-07-22): Korean outlets paraphrase titles
# heavily — same-story pairs cluster around J 0.37-0.55 while observed
# different-story pairs sit at <= 0.36.
JACCARD_THRESHOLD = 0.45
# Tiny signatures need near-exact overlap ("CES 2026" vs "CES 2026 preview").
MIN_SIG_SHINGLES = 4
SMALL_SIG_JACCARD = 0.85
# Shingles shared by more items than this are useless join keys — but the cap
# must exceed any plausible single-story copy count, or mega-stories fragment.
PRUNE_DF = 100
# Negative lookaheads for hangul substring terms that shadow unrelated words.
HANGUL_TERM_EXCLUSIONS = {"메타": "버스|데이터|인지|그린"}

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
NORM_RE = re.compile(r"[^0-9a-z가-힣]+")
ASCII_TOKEN_RE = re.compile(r"[0-9a-z]+")


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
    normalized = normalize_title(title) or title  # avoid shared id for e.g. CJK-only titles
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]


def parse_published(entry):
    for attr in ("published_parsed", "updated_parsed"):
        parsed = entry.get(attr)
        if parsed:
            try:
                # feedparser normalizes struct_time to UTC; timegm keeps it UTC
                # (mktime would reinterpret it in the machine's local timezone)
                return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)
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
                # Letter-only lookarounds instead of \b: Hangul counts as \w, so
                # \bgpu\b would miss "gpu를"/"hbm4를" — the common case in Korean text.
                patterns.append(re.compile(r"(?<![a-z])" + re.escape(kw) + r"(?![a-z])"))
            else:
                patterns.append(re.compile(re.escape(kw)))
        compiled[theme] = patterns
    return compiled


def classify(text, compiled_rules):
    lowered = text.lower()
    return [t for t, pats in compiled_rules.items() if any(p.search(lowered) for p in pats)]


def strip_gn_publisher(title):
    """Google News titles end with ' - Publisher' (publisher itself may contain hyphens)."""
    return title.rsplit(" - ", 1)[0].strip() if " - " in title else title


def is_google_news(item):
    return item["source_id"].startswith("gn-")


def merge_items(existing, incoming, first_seen_at):
    """Merge items by id, upgrading a Google News copy to a direct-source copy."""
    merged = {}
    for item in existing:
        item = dict(item)
        item.setdefault("first_seen_at", item["published"])
        merged[item["id"]] = item

    for item in incoming:
        item = dict(item)
        current = merged.get(item["id"])
        if current is None:
            item["first_seen_at"] = first_seen_at
            merged[item["id"]] = item
        elif is_google_news(current) and not is_google_news(item):
            item["first_seen_at"] = current["first_seen_at"]
            merged[item["id"]] = item
    return list(merged.values())


def select_items(items, now_str, cutoff, max_items=MAX_ITEMS,
                 gn_per_source_max=GN_PER_SOURCE_MAX, gn_pool_max=GN_POOL_MAX):
    """Keep all recent direct items first, then fill a bounded Google News pool."""
    recent = []
    for item in items:
        item = dict(item)
        if item["published"] > now_str:
            item["published"] = now_str
        if item["published"] >= cutoff:
            recent.append(item)

    direct = sorted(
        (item for item in recent if not is_google_news(item)),
        key=lambda item: item["published"], reverse=True,
    )[:max_items]
    remaining = max(0, max_items - len(direct))
    gn_budget = min(gn_pool_max, remaining)
    per_source = {}
    google_news = []
    for item in sorted(
        (item for item in recent if is_google_news(item)),
        key=lambda item: item["published"], reverse=True,
    ):
        source_id = item["source_id"]
        if per_source.get(source_id, 0) >= gn_per_source_max:
            continue
        google_news.append(item)
        per_source[source_id] = per_source.get(source_id, 0) + 1
        if len(google_news) >= gn_budget:
            break

    selected = direct + google_news
    selected.sort(key=lambda item: item["published"], reverse=True)
    return selected


def title_shingles(title):
    """Latin/digit tokens as whole shingles, hangul(-mixed) runs as char-bigrams."""
    grams = set()
    for token in NORM_RE.split(title.lower()):
        if not token:
            continue
        if ASCII_TOKEN_RE.fullmatch(token) or len(token) == 1:
            grams.add(token)
        else:
            for i in range(len(token) - 1):
                grams.add(token[i:i + 2])
    return grams


def item_tier(item, tiers):
    return tiers.get(item["source_id"], DEFAULT_TIER)


def representative(members, tiers):
    """Item-intrinsic pick so the result never depends on input order."""
    def key(member):
        return (
            item_tier(member, tiers),
            is_google_news(member),
            member.get("first_seen_at") or member["published"],
            member["id"],
        )
    return min(members, key=key)


def cluster_items(items, tiers):
    """Group near-duplicate titles; returns {item_id: representative item_id}.

    The candidate-pair set is determined by inverted-index content and the
    final partition is the connected components of the merge graph, so the
    mapping is permutation-invariant for a given item set.
    """
    sigs = [title_shingles(item["title"]) for item in items]

    index = {}
    for pos, sig in enumerate(sigs):
        for gram in sig:
            index.setdefault(gram, []).append(pos)

    parent = list(range(len(items)))

    def find(pos):
        while parent[pos] != pos:
            parent[pos] = parent[parent[pos]]
            pos = parent[pos]
        return pos

    checked = set()
    for positions in index.values():
        if len(positions) > PRUNE_DF:
            continue
        for a in range(len(positions)):
            for b in range(a + 1, len(positions)):
                pair = (positions[a], positions[b])
                if pair in checked:
                    continue
                checked.add(pair)
                si, sj = sigs[pair[0]], sigs[pair[1]]
                threshold = (
                    SMALL_SIG_JACCARD
                    if min(len(si), len(sj)) < MIN_SIG_SHINGLES
                    else JACCARD_THRESHOLD
                )
                union = len(si) + len(sj) - len(si & sj)
                if union and len(si & sj) / union >= threshold:
                    root_a, root_b = find(pair[0]), find(pair[1])
                    if root_a != root_b:
                        parent[root_b] = root_a

    groups = {}
    for pos in range(len(items)):
        groups.setdefault(find(pos), []).append(pos)

    mapping = {}
    for positions in groups.values():
        members = [items[pos] for pos in positions]
        rep_id = representative(members, tiers)["id"]
        for member in members:
            mapping[member["id"]] = rep_id
    return mapping


def compile_company_terms(companies):
    """Match semantics mirror make_digest.term_matches: ASCII terms bounded by
    non-alphanumerics, non-ASCII terms as substrings. Tickers are matched
    case-sensitively (prose "mu"/"meta" must not hit MU/META)."""
    compiled = []
    for company in companies:
        terms = [(company["name"], False), (company["ticker"], True)]
        terms += [(alias, False) for alias in company.get("aliases", [])]
        patterns = []
        for term, case_sensitive in terms:
            if not term:
                continue
            if term.isascii():
                pattern = rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])"
            else:
                exclusion = HANGUL_TERM_EXCLUSIONS.get(term)
                pattern = re.escape(term) + (rf"(?!{exclusion})" if exclusion else "")
            patterns.append(re.compile(pattern, 0 if case_sensitive else re.IGNORECASE))
        compiled.append((company["id"], patterns))
    return compiled


def match_company_ids(text, compiled_companies):
    return [
        company_id
        for company_id, patterns in compiled_companies
        if any(pattern.search(text) for pattern in patterns)
    ]


def score_cluster(members, tiers):
    """Tier-weighted count of distinct outlet names plus a single watchlist bonus.

    One outlet counted once at its best tier, so a direct copy outranks the
    same outlet's Google News copy and GN duplicates don't inflate the score.
    """
    weights = {}
    for member in members:
        name = member["source"].casefold().strip()
        weight = TIER_WEIGHTS[item_tier(member, tiers)]
        weights[name] = max(weights.get(name, 0.0), weight)
    score = sum(weights[name] for name in sorted(weights))
    if any(member["company_ids"] for member in members):
        score += WATCHLIST_BONUS
    return score


def enrich_items(items, tiers, companies):
    """Annotate items with company_ids, cluster_id, and score.

    Pure function of (items, tiers, companies) and always reassigns all three
    fields: select_items copies and merge upgrades can carry stale annotations
    from a previous run, and determinism keeps the no-change fast path alive.
    """
    compiled = compile_company_terms(companies)
    enriched = []
    for item in items:
        item = dict(item)
        item["company_ids"] = match_company_ids(
            f"{item['title']} {item['snippet']}", compiled
        )
        enriched.append(item)

    mapping = cluster_items(enriched, tiers)
    groups = {}
    for item in enriched:
        item["cluster_id"] = mapping[item["id"]]
        groups.setdefault(item["cluster_id"], []).append(item)
    scores = {
        cluster_id: score_cluster(members, tiers)
        for cluster_id, members in groups.items()
    }
    for item in enriched:
        item["score"] = scores[item["cluster_id"]]
    return enriched


def collect(source, compiled_rules):
    resp = requests.get(feed_url(source), headers={"User-Agent": UA}, timeout=TIMEOUT)
    resp.raise_for_status()
    parsed = feedparser.parse(resp.content)
    is_gn = bool(source.get("google_news"))
    items = []
    for entry in parsed.entries:
        title = clean_text(entry.get("title", ""))
        url = entry.get("link", "")
        if not title or not url.startswith(("http://", "https://")):
            continue  # also rejects javascript:/data: links from a hostile feed
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
    # No fallback on purpose: a silent empty watchlist would flip every score
    # and oscillate the runtime-data snapshot between runs.
    companies = json.loads(COMPANIES_PATH.read_text(encoding="utf-8"))["companies"]
    tiers = {source["id"]: source["tier"] for source in config["sources"]}
    compiled_rules = compile_rules(config["keyword_rules"])
    run_now = now_utc()
    run_now_str = iso(run_now)

    stored_items = []
    if OUT_PATH.exists():
        stored_items = json.loads(OUT_PATH.read_text(encoding="utf-8")).get("items", [])
    merged = merge_items(stored_items, [], run_now_str)

    failures = []
    for source in config["sources"]:
        try:
            fetched = collect(source, compiled_rules)
        except Exception as exc:  # per-source isolation: one bad feed never kills the run
            failures.append(f"{source['id']}: {exc}")
            continue
        old_ids = {item["id"] for item in merged}
        merged = merge_items(merged, fetched, run_now_str)
        fresh = sum(item["id"] not in old_ids for item in fetched)
        print(f"{source['id']}: {len(fetched)} items, {fresh} new")

    if failures:
        print("failed sources:\n  " + "\n  ".join(failures), file=sys.stderr)
    if len(failures) == len(config["sources"]):
        print("all sources failed, aborting", file=sys.stderr)
        return 1

    cutoff = iso(run_now - timedelta(hours=WINDOW_HOURS))
    items = enrich_items(select_items(merged, run_now_str, cutoff), tiers, companies)

    if items == stored_items:
        print(f"no change ({len(items)} items in window)")
        return 0

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"generated_at": run_now_str, "items": items}
    OUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(f"wrote {len(items)} items ({len(items) - len(stored_items):+d})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
