# JayBrief

Personal stock-investing news PWA — themed feed (semiconductors / software tech) plus four LLM-written decision-support briefings per day in Korean.

- Deploy: GitHub Actions assembles and publishes a GitHub Pages artifact.
- No application server: the deployed app is a pure client that reads generated JSON.
- Sister project: [jayfit](https://github.com/jaeyoun98/jayfit) (same PWA + Pages pattern).

## How it works

```
pages.yml
  scheduled refresh -> fetch feeds -> optional Gemini digest
                    -> replace the one-commit runtime-data snapshot
                    -> combine main shell + runtime data
                    -> deploy a GitHub Pages artifact
```

Schedules are best-effort: GitHub-hosted cron routinely lands late, so the 20-minute feed schedule effectively refreshes about once an hour, and digest editions can start 30-60 minutes after their slot (measured 2026-07-20, median 65 min between feed runs).

The PWA (vanilla HTML/CSS/JS) reads generated JSON with `cache: 'no-cache'` and renders three tabs: 피드 (article list), 브리핑 (LLM digest), and 주요 이벤트 (watchlist calendar and agenda).
Application history stays on `main`; generated JSON lives on the force-with-lease protected `runtime-data` branch as one rolling root commit, so recurring feed and digest updates do not inflate `main` history.

## Setup

1. Create a free Gemini API key in [Google AI Studio](https://aistudio.google.com/).
2. Add it as the `GEMINI_API_KEY` repo secret (`gh secret set GEMINI_API_KEY`).
3. Optional: override the model with a `GEMINI_MODEL` env/variable (default `gemini-3.1-flash-lite`).

Without the secret, the feed and event calendar still work; only digest generation is skipped. A failed or invalid Gemini response leaves the last good digest untouched.

## Development

```
pip install -r requirements.txt
python scripts/fetch_feeds.py          # create/refresh ignored data/feed.json
GEMINI_API_KEY=... python scripts/make_digest.py
python -m http.server 8000             # then open http://localhost:8000
```

The `data/` directory is runtime output and is intentionally ignored except for `.gitkeep`.
Run the fetcher locally before developing views that require feed or digest data.

Conventions and data contracts: see [CLAUDE.md](CLAUDE.md).
