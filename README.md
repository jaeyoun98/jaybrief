# JayBrief

Personal stock-investing news PWA — themed feed (semiconductors / software tech) plus an LLM-written daily briefing in Korean.

- Deploy: GitHub Pages, auto-served from `main`.
- No server: GitHub Actions collects data into JSON files; the app is a pure client.
- Sister project: [jayfit](https://github.com/jaeyoun98/jayfit) (same PWA + Pages pattern).

## How it works

```
feed.yml (every 20 minutes)
  scripts/fetch_feeds.py : sources.json -> fetch RSS -> theme classify
                           -> dedup -> 72h rolling window -> data/feed.json
digest.yml (07:30 / 12:30 / 18:30 / 21:00 KST)
  scripts/make_digest.py : new items + watchlist/events + direct URLs
                           -> Gemini structured output
                           -> current digest + indexed archive
```

The PWA (vanilla HTML/CSS/JS) reads committed JSON with `cache: 'no-cache'` and renders three tabs: 피드 (article list), 브리핑 (LLM digest), and 주요 이벤트 (watchlist calendar and agenda).

## Setup

1. Create a free Gemini API key in [Google AI Studio](https://aistudio.google.com/).
2. Add it as the `GEMINI_API_KEY` repo secret (`gh secret set GEMINI_API_KEY`).
3. Optional: override the model with a `GEMINI_MODEL` env/variable (default `gemini-3.1-flash-lite`).

Without the secret, the feed and event calendar still work; only digest generation is skipped. A failed or invalid Gemini response leaves the last good digest untouched.

## Development

```
pip install -r requirements.txt
python scripts/fetch_feeds.py          # refresh data/feed.json
GEMINI_API_KEY=... python scripts/make_digest.py
python -m http.server 8000             # then open http://localhost:8000
```

Conventions and data contracts: see [CLAUDE.md](CLAUDE.md).
