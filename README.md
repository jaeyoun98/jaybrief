# JayBrief

Personal stock-investing news PWA — themed feed (semiconductors / software tech) plus an LLM-written daily briefing in Korean.

- Deploy: GitHub Pages, auto-served from `main`.
- No server: GitHub Actions collects data into JSON files; the app is a pure client.
- Sister project: [jayfit](https://github.com/jaeyoun98/jayfit) (same PWA + Pages pattern).

## How it works

```
feed.yml (hourly cron)
  scripts/fetch_feeds.py : sources.json -> fetch RSS -> theme classify
                           -> dedup -> 72h rolling window -> data/feed.json
digest.yml (07:30 / 18:30 KST)
  scripts/make_digest.py : recent items -> Gemini (free tier)
                           -> data/digest.json + data/digests/ archive
```

The PWA (vanilla HTML/CSS/JS) reads `data/*.json` with `cache: 'no-cache'` and renders two tabs: 피드 (article list with theme filters) and 브리핑 (LLM digest).

## Setup

1. Create a free Gemini API key in [Google AI Studio](https://aistudio.google.com/).
2. Add it as the `GEMINI_API_KEY` repo secret (`gh secret set GEMINI_API_KEY`).
3. Optional: override the model with a `GEMINI_MODEL` env/variable (default `gemini-3.1-flash-lite`).

Without the secret, the feed still updates hourly; only the digest is skipped.

## Development

```
pip install -r requirements.txt
python scripts/fetch_feeds.py          # refresh data/feed.json
GEMINI_API_KEY=... python scripts/make_digest.py
python -m http.server 8000             # then open http://localhost:8000
```

Conventions and data contracts: see [CLAUDE.md](CLAUDE.md).
