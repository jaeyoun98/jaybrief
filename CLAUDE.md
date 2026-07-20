# JayBrief

Personal stock-investing news PWA: themed feed (semiconductors / software tech) + LLM daily digest in Korean.

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
.github/workflows/feed.yml    (every 20 min) -> scripts/fetch_feeds.py -> data/feed.json
.github/workflows/digest.yml  (07:30/12:30/18:30/21:00 KST) -> scripts/make_digest.py -> data/digest.json (+ data/digests/ archive)
GitHub Pages serves repo root; PWA fetches data/*.json with cache:'no-cache'
```

- `fetch_feeds.py`: reads `sources.json`, fetches RSS/Atom, classifies items into themes, dedups by normalized title, keeps a rolling 72 h window (cap 800), writes only when the item set changed (avoids no-op commits).
- `make_digest.py`: summarizes recent feed items per theme via Gemini API (free tier). Needs `GEMINI_API_KEY` repo secret; exits 0 with a notice when the secret is missing so the workflow stays green before setup. Model override: `GEMINI_MODEL` env (default `gemini-3.1-flash-lite`).
- Data JSONs are committed by github-actions[bot]; both workflows share one concurrency group to avoid push races.

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
    "published": "ISO-8601 UTC",
    "lang": "ko" | "en",
    "snippet": "plain text <= 280 chars, may be empty"
  }]
}
```

`data/digest.json`:

```json
{
  "generated_at": "ISO-8601 UTC", "date": "YYYY-MM-DD (KST)",
  "edition": "morning" | "noon" | "evening" | "night", "model": "...",
  "themes": [{
    "theme": "semi", "overview": "2-3 sentences (Korean)",
    "stories": [{ "headline": "...", "body": "...", "article_ids": ["..."], "importance": 1-3 }]
  }]
}
```

`sources.json`: per source either fixed `themes: [...]` (no classification) or `classify: true` + `fallback_themes` (`[]` = drop items that match no keyword rule). Google News query sources use a `google_news: {q, hl, gl, ceid}` object instead of `feed`; the fetcher builds the URL and strips the trailing " - publisher" from titles.

## Source curation

Source list curated 2026-07-20 (all feeds verified alive; see nous wiki `personal-app-dev`/session log for the vetting).
When adding a source: verify the feed returns XML with fresh `pubDate`s first; prefer specialist low-noise outlets; general outlets get `classify: true`.
