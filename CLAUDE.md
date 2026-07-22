# JayBrief

Personal stock-investing news PWA: themed feed (semiconductors / software tech) + LLM decision-support briefings in Korean.

## Conventions

- UI strings: Korean. Code, comments, docs, commit messages: English.
- Commit messages: one-line imperative. No AI trailers (`Co-Authored-By` etc.) — author is the user alone.
- Frontend: vanilla HTML/CSS/JS, no frameworks, no build step. Pipeline: Python 3.11+ (`requirements.txt`).
- All asset/data paths relative (`./`) — the app is served under a repo subpath on GitHub Pages.

## Rename policy

The app display name lives in exactly three places: `manifest.webmanifest` (`name`/`short_name`), `<title>` in `index.html`, and `APP_NAME` in `app.js`.
Renaming = change those three + rename the GitHub repo (Pages URL follows the repo name; installed PWAs must be re-added to the home screen).
localStorage keys are name-independent (`jb.*`) on purpose.

## Architecture

```
.github/workflows/pages.yml -> refresh feed / optional digest -> rolling runtime-data branch
main shell + runtime-data/data -> GitHub Pages artifact -> deployed PWA
```

- `fetch_feeds.py`: reads `sources.json`, fetches RSS/Atom, classifies items into themes, dedups by normalized title, and keeps a rolling 72 h window. Direct sources take priority; Google News is capped at 60 items per source and 240 overall within the 800-item total cap. It also clusters near-duplicate titles (shingle Jaccard + union-find) and scores each cluster from source tiers, distinct outlet count, and watchlist mentions — deterministically from the item set alone (no timestamps in scores), so re-running on unchanged input is a byte-identical no-op. ko/en copies of one story never cluster together (no cross-language matching), and Google News items without an outlet name all count as one "Google News" source.
- `make_digest.py`: combines newly observed items (`first_seen_at`), the public watchlist, upcoming events, and up to 8 non-paywalled direct article URLs. Gemini returns schema-constrained decision-support fields; semantic validation happens before the current/archived digest is written. Needs `GEMINI_API_KEY`; model override: `GEMINI_MODEL` (default `gemini-3.1-flash-lite`).
- The feed and event calendar work without Gemini. API, truncation, JSON, or semantic validation failures preserve the last good digest because no output file is written before validation succeeds.
- Generated JSON is not tracked on `main`. The `runtime-data` branch is replaced with a one-commit root snapshot using `--force-with-lease`, then combined with the `main` shell in a Pages artifact. One workflow concurrency group serializes refresh and deployment.
- Cron cadences are declared, not guaranteed: GitHub schedule events are best-effort and measured delivery is roughly hourly for the 20-minute feed cron, with digest slots starting 30-60 min late. The pipeline tolerates this (72 h window, `first_seen_at` incremental digests) — do not tighten the cron to compensate.
- `companies.json` is the public watchlist; `events.json` is a manually verified calendar. If private portfolio fields are added, quantities and cost basis must remain in localStorage and must not be committed or sent to Gemini.
- For local development, run `fetch_feeds.py` to populate the ignored `data/` directory before starting the static server.

## Data contracts (keep scripts and app.js in sync)

`data/feed.json`:

```json
{
  "generated_at": "ISO-8601 UTC",
  "items": [{
    "id": "sha1(normalized title)[:16]",
    "title": "...", "url": "...",
    "source": "디일렉", "source_id": "thelec",
    "themes": ["semi"],           // "semi" | "sw", multi allowed
    "published": "ISO-8601 UTC", "first_seen_at": "ISO-8601 UTC",
    "lang": "ko" | "en",
    "snippet": "plain text <= 280 chars, may be empty",
    "cluster_id": "item id of the cluster representative (shared by near-duplicate stories; == id for singletons)",
    "company_ids": ["nvidia"],    // watchlist matches, companies.json order
    "score": 4.0                  // cluster importance, same value on every member
  }]
}
```

Cluster score = sum over distinct outlet names of the best tier weight (tier 1 = 3.0, tier 2 = 2.0, tier 3/Google News = 1.0) + 1.0 once if any member mentions a watchlist company. The app's 주요 view shows clusters with score >= 3.0 and hides its toggle when items carry no scores (stale cached feed).

`data/digest.json`:

```json
{
  "generated_at": "ISO-8601 UTC", "date": "YYYY-MM-DD (KST)",
  "edition": "morning" | "noon" | "evening" | "night", "model": "...",
  "themes": [{
    "theme": "semi", "overview": "2-3 sentences (Korean)",
    "stories": [{
      "headline": "...", "facts": ["..."], "interpretation": "...",
      "affected_company_ids": ["nvidia"],
      "event_type": "earnings|guidance|product|policy|supply_chain|market|other",
      "impact": "positive|negative|mixed|unclear",
      "horizon": "immediate|quarter|long_term",
      "confidence": "high|medium|low", "watch_next": "...",
      "upcoming_event_ids": ["nvidia-fy27-q2"],
      "article_ids": ["..."], "importance": 1-3
    }]
  }],
  "articles": [{ "id": "...", "title": "...", "url": "...", "source": "..." }]
}
```

`data/digests/index.json` lists the 60 newest archive entries. Unreferenced archive files are pruned, and each digest snapshots its cited article links so archives remain useful after items expire from the rolling feed.

`sources.json`: per source either fixed `themes: [...]` (no classification) or `classify: true` + `fallback_themes` (`[]` = drop items that match no keyword rule). Every source declares `tier` (1 = specialist direct, 2 = general direct, 3 = Google News query) — the scoring weight input. Google News query sources use a `google_news: {q, hl, gl, ceid}` object instead of `feed`; the fetcher builds the URL and strips the trailing " - publisher" from titles.

`events.json`: manually verified events with `type` (`earnings` | `conference` | `macro`), ISO `start_at`, optional `end_at`, `all_day`, `status`, `company_ids`, themes, importance, official `source_url`, and a short note. Root-level config/data files use the same network-first offline fallback as generated `data/*.json`.

## Source curation

Source list curated 2026-07-20 (all feeds verified alive at curation time).
When adding a source: verify the feed returns XML with fresh `pubDate`s first; prefer specialist low-noise outlets; general outlets get `classify: true`.
