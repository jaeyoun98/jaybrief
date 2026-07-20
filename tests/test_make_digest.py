import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from scripts.make_digest import (
    DIGEST_SCHEMA,
    ROOT,
    build_archive_index,
    call_gemini,
    matching_company_ids,
    recent_items,
    select_direct_urls,
    upcoming_events,
    validate_themes,
)


def article(item_id, **extra):
    value = {
        "id": item_id,
        "title": item_id,
        "url": f"https://example.com/{item_id}",
        "source": "Example",
        "themes": ["semi"],
        "published": "2026-07-19T10:00:00Z",
        "snippet": "",
    }
    value.update(extra)
    return value


class DigestInputTest(unittest.TestCase):
    def test_recent_window_uses_first_seen_at(self):
        late_discovery = article(
            "late",
            published="2026-07-01T00:00:00Z",
            first_seen_at="2026-07-20T10:00:00Z",
        )
        self.assertEqual(
            recent_items([late_discovery], "semi", "2026-07-20T09:00:00Z"),
            [late_discovery],
        )

    def test_recent_window_prioritizes_observation_time_not_publish_order(self):
        earlier_observations = [
            article(
                f"newer-published-{index}",
                published="2026-07-20T11:00:00Z",
                first_seen_at="2026-07-20T09:30:00Z",
            )
            for index in range(120)
        ]
        late_discovery = article(
            "late",
            published="2026-07-19T00:00:00Z",
            first_seen_at="2026-07-20T10:00:00Z",
        )
        selected = recent_items(
            [*earlier_observations, late_discovery],
            "semi",
            "2026-07-20T09:00:00Z",
        )
        self.assertIn(late_discovery, selected)

    def test_company_matching_uses_names_aliases_and_ticker_boundaries(self):
        companies = [{
            "id": "amd", "name": "AMD", "ticker": "AMD",
            "aliases": ["Advanced Micro Devices"],
        }]
        self.assertEqual(
            matching_company_ids(article("a", title="Advanced Micro Devices raises guidance"), companies),
            ["amd"],
        )
        self.assertEqual(
            matching_company_ids(article("b", title="Example ramdisk release"), companies),
            [],
        )

    def test_url_context_excludes_google_news_paywalls_and_duplicates(self):
        items = [
            article("direct", url="https://example.com/story", first_seen_at="2026-07-20T10:00:00Z"),
            article("duplicate", url="https://example.com/story", first_seen_at="2026-07-20T09:00:00Z"),
            article("google", url="https://news.google.com/rss/articles/abc"),
            article("paywall", url="https://www.wsj.com/articles/abc"),
        ]
        self.assertEqual([item["id"] for item in select_direct_urls(items)], ["direct"])

    def test_url_context_prioritizes_watchlist_matches(self):
        companies = [{"id": "amd", "name": "AMD", "ticker": "AMD", "aliases": []}]
        items = [
            article("new-general", title="General market update", first_seen_at="2026-07-20T11:00:00Z"),
            article("older-amd", title="AMD product update", first_seen_at="2026-07-20T10:00:00Z"),
        ]
        selected = select_direct_urls(items, companies, max_urls=1)
        self.assertEqual([item["id"] for item in selected], ["older-amd"])

    def test_upcoming_events_obeys_lookahead(self):
        events = [
            {"id": "soon", "start_at": "2026-07-22"},
            {"id": "late", "start_at": "2026-09-30"},
        ]
        now = datetime(2026, 7, 20, tzinfo=timezone.utc)
        self.assertEqual([event["id"] for event in upcoming_events(events, now)], ["soon"])


class DigestOutputTest(unittest.TestCase):
    @patch("scripts.make_digest.requests.post")
    def test_gemini_request_uses_schema_and_optional_url_context(self, post):
        response = post.return_value
        response.status_code = 200
        response.json.return_value = {
            "candidates": [{
                "finishReason": "STOP",
                "content": {"parts": [{"text": '{"themes": []}'}]},
            }],
        }
        self.assertEqual(call_gemini("secret", "model", "prompt", True), '{"themes": []}')
        request = post.call_args.kwargs
        self.assertEqual(request["headers"], {"x-goog-api-key": "secret"})
        self.assertEqual(request["json"]["generationConfig"]["responseSchema"], DIGEST_SCHEMA)
        self.assertEqual(request["json"]["tools"], [{"url_context": {}}])

    def test_archive_index_replaces_same_edition_and_sorts_newest_first(self):
        existing = {"digests": [{
            "path": "data/digests/2026-07-20-morning.json",
            "generated_at": "2026-07-20T00:00:00Z",
            "date": "2026-07-20",
            "edition": "morning",
        }]}
        digest = {
            "generated_at": "2026-07-20T03:30:00Z",
            "date": "2026-07-20",
            "edition": "noon",
        }
        archive = ROOT / "data/digests/2026-07-20-noon.json"
        result = build_archive_index(existing, digest, archive)
        self.assertEqual(
            [entry["edition"] for entry in result["digests"]],
            ["noon", "morning"],
        )

    def test_removes_unknown_ids_and_story_without_evidence(self):
        base_story = {
            "headline": "h",
            "facts": ["f"],
            "interpretation": "i",
            "affected_company_ids": ["amd", "invented"],
            "event_type": "guidance",
            "impact": "positive",
            "horizon": "quarter",
            "confidence": "medium",
            "watch_next": "w",
            "upcoming_event_ids": ["amd-q2", "invented"],
            "article_ids": ["known", "invented"],
            "importance": 3,
        }
        themes = [
            {"theme": "semi", "overview": "semi", "stories": [base_story.copy()]},
            {"theme": "sw", "overview": "sw", "stories": [{**base_story, "article_ids": ["invented"]}]},
        ]
        result = validate_themes(themes, {"known"}, {"amd"}, {"amd-q2"})
        story = result[0]["stories"][0]
        self.assertEqual(story["article_ids"], ["known"])
        self.assertEqual(story["affected_company_ids"], ["amd"])
        self.assertEqual(story["upcoming_event_ids"], ["amd-q2"])
        self.assertEqual(result[1]["stories"], [])

    def test_requires_exactly_two_known_themes(self):
        with self.assertRaises(ValueError):
            validate_themes([{"theme": "semi"}], set(), set(), set())

    def test_rejects_malformed_story_before_write(self):
        themes = [
            {"theme": "semi", "overview": "semi", "stories": [{"headline": "missing"}]},
            {"theme": "sw", "overview": "sw", "stories": []},
        ]
        with self.assertRaises(ValueError):
            validate_themes(themes, set(), set(), set())


if __name__ == "__main__":
    unittest.main()
