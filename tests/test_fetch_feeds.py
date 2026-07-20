import unittest

from scripts.fetch_feeds import merge_items, select_items


NOW = "2026-07-20T12:00:00Z"
CUTOFF = "2026-07-17T12:00:00Z"


def item(item_id, source_id, published="2026-07-20T10:00:00Z", **extra):
    value = {
        "id": item_id,
        "title": item_id,
        "url": f"https://example.com/{item_id}",
        "source": source_id,
        "source_id": source_id,
        "themes": ["semi"],
        "published": published,
        "lang": "en",
        "snippet": "",
    }
    value.update(extra)
    return value


class MergeItemsTest(unittest.TestCase):
    def test_backfills_legacy_first_seen_at(self):
        merged = merge_items([item("legacy", "direct")], [], NOW)
        self.assertEqual(merged[0]["first_seen_at"], merged[0]["published"])

    def test_direct_source_replaces_google_news_and_preserves_first_seen(self):
        google = item("same", "gn-en-semi", first_seen_at="2026-07-20T09:00:00Z")
        direct = item("same", "thelec", snippet="full summary")
        merged = merge_items([google], [direct], NOW)
        self.assertEqual(merged[0]["source_id"], "thelec")
        self.assertEqual(merged[0]["snippet"], "full summary")
        self.assertEqual(merged[0]["first_seen_at"], "2026-07-20T09:00:00Z")

    def test_google_news_never_replaces_direct_source(self):
        direct = item("same", "thelec", first_seen_at="2026-07-20T09:00:00Z")
        google = item("same", "gn-en-semi")
        self.assertEqual(merge_items([direct], [google], NOW)[0], direct)


class SelectItemsTest(unittest.TestCase):
    def test_applies_google_news_quotas_to_final_merged_set(self):
        direct = [item(f"direct-{n}", "thelec") for n in range(10)]
        google = [item(f"gn-a-{n}", "gn-en-semi") for n in range(80)]
        google += [item(f"gn-b-{n}", "gn-kr-semi") for n in range(80)]
        selected = select_items(direct + google, NOW, CUTOFF, max_items=200,
                                gn_per_source_max=60, gn_pool_max=100)
        source_ids = [value["source_id"] for value in selected]
        self.assertEqual(len(selected), 110)
        self.assertEqual(source_ids.count("gn-en-semi"), 60)
        self.assertEqual(source_ids.count("gn-kr-semi"), 40)

    def test_direct_items_take_capacity_before_google_news(self):
        direct = [item(f"direct-{n}", "thelec") for n in range(5)]
        google = [item(f"gn-{n}", "gn-en-semi") for n in range(5)]
        selected = select_items(direct + google, NOW, CUTOFF, max_items=6,
                                gn_per_source_max=60, gn_pool_max=240)
        self.assertEqual(sum(not v["source_id"].startswith("gn-") for v in selected), 5)
        self.assertEqual(sum(v["source_id"].startswith("gn-") for v in selected), 1)

    def test_truncates_direct_items_by_recency_when_they_exceed_capacity(self):
        values = [
            item("new", "thelec", "2026-07-20T11:00:00Z"),
            item("mid", "thelec", "2026-07-20T10:00:00Z"),
            item("old", "thelec", "2026-07-20T09:00:00Z"),
        ]
        selected = select_items(values, NOW, CUTOFF, max_items=2)
        self.assertEqual([value["id"] for value in selected], ["new", "mid"])

    def test_second_pass_produces_identical_payload(self):
        legacy = item("legacy", "thelec")
        first = select_items(merge_items([legacy], [], NOW), NOW, CUTOFF)
        second = select_items(merge_items(first, [], NOW), NOW, CUTOFF)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
