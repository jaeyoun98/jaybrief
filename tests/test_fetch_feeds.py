import unittest

from scripts.fetch_feeds import (
    cluster_items,
    compile_company_terms,
    enrich_items,
    match_company_ids,
    merge_items,
    representative,
    score_cluster,
    select_items,
    title_shingles,
)


NOW = "2026-07-20T12:00:00Z"
CUTOFF = "2026-07-17T12:00:00Z"

TIERS = {"thelec": 1, "etnews": 2, "gn-en-semi": 3, "gn-kr-semi": 3}

COMPANIES = [
    {"id": "nvidia", "name": "NVIDIA", "ticker": "NVDA", "aliases": ["엔비디아"]},
    {"id": "micron", "name": "Micron", "ticker": "MU", "aliases": ["마이크론"]},
    {"id": "meta", "name": "Meta", "ticker": "META", "aliases": ["메타"]},
]


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
        first = enrich_items(
            select_items(merge_items([legacy], [], NOW), NOW, CUTOFF), TIERS, COMPANIES
        )
        second = enrich_items(
            select_items(merge_items(first, [], NOW), NOW, CUTOFF), TIERS, COMPANIES
        )
        self.assertEqual(first, second)
        for field in ("cluster_id", "company_ids", "score"):
            self.assertIn(field, first[0])


class TitleShinglesTest(unittest.TestCase):
    def test_latin_tokens_hangul_bigrams_and_unigrams(self):
        self.assertEqual(
            title_shingles("AI 반도체 붐, 칩 시대"),
            {"ai", "반도", "도체", "붐", "칩", "시대"},
        )

    def test_punctuation_only_title_yields_empty_set(self):
        self.assertEqual(title_shingles("?!... —"), set())


class ClusterItemsTest(unittest.TestCase):
    def test_groups_paraphrased_titles(self):
        a = item("a", "thelec", title="TSMC's $265 billion US spending driven by demand and rivals, CFO says")
        b = item("b", "etnews", title="TSMC's US$265 bil US spending driven by demand and rivals, CFO says")
        mapping = cluster_items([a, b], TIERS)
        self.assertEqual(mapping["a"], mapping["b"])

    def test_keeps_unrelated_titles_apart(self):
        a = item("a", "thelec", title="Samsung begins HBM4 mass production")
        b = item("b", "etnews", title="Intel delays Ohio fab construction")
        mapping = cluster_items([a, b], TIERS)
        self.assertNotEqual(mapping["a"], mapping["b"])

    def test_short_signatures_require_near_exact_overlap(self):
        a = item("a", "thelec", title="CES 2026")
        b = item("b", "etnews", title="CES 2026 preview")
        c = item("c", "gn-en-semi", title="CES 2026!")
        mapping = cluster_items([a, b, c], TIERS)
        self.assertNotEqual(mapping["a"], mapping["b"])  # 0.67 < 0.85
        self.assertEqual(mapping["a"], mapping["c"])  # identical shingles

    def test_empty_signature_items_stay_singletons(self):
        a = item("a", "thelec", title="?!")
        b = item("b", "etnews", title="...")
        mapping = cluster_items([a, b], TIERS)
        self.assertEqual(mapping, {"a": "a", "b": "b"})

    def test_mapping_is_permutation_invariant(self):
        values = [
            item("a", "thelec", title="Samsung begins HBM4 mass production"),
            item("b", "etnews", title="Samsung begins HBM4 mass production today"),
            item("c", "gn-en-semi", title="Intel delays Ohio fab construction"),
        ]
        forward = cluster_items(values, TIERS)
        backward = cluster_items(list(reversed(values)), TIERS)
        self.assertEqual(forward, backward)


class RepresentativeTest(unittest.TestCase):
    def test_lower_tier_wins(self):
        members = [item("b", "etnews"), item("a", "thelec")]
        self.assertEqual(representative(members, TIERS)["id"], "a")

    def test_direct_source_beats_google_news_at_equal_tier(self):
        members = [item("a", "gn-en-semi"), item("b", "unknown-direct")]
        self.assertEqual(representative(members, TIERS)["id"], "b")

    def test_earlier_first_seen_wins(self):
        members = [
            item("a", "thelec", first_seen_at="2026-07-20T10:00:00Z"),
            item("b", "thelec", first_seen_at="2026-07-20T09:00:00Z"),
        ]
        self.assertEqual(representative(members, TIERS)["id"], "b")

    def test_id_breaks_remaining_ties(self):
        members = [item("b", "thelec"), item("a", "thelec")]
        self.assertEqual(representative(members, TIERS)["id"], "a")


class ScoreClusterTest(unittest.TestCase):
    def test_same_outlet_name_counted_once_at_best_tier(self):
        direct = item("a", "etnews", source="전자신문", company_ids=[])
        google = item("b", "gn-kr-semi", source="전자신문", company_ids=[])
        self.assertEqual(score_cluster([direct, google], TIERS), 2.0)

    def test_distinct_outlets_sum_their_tier_weights(self):
        members = [
            item("a", "thelec", source="디일렉", company_ids=[]),
            item("b", "gn-kr-semi", source="조선일보", company_ids=[]),
        ]
        self.assertEqual(score_cluster(members, TIERS), 4.0)

    def test_watchlist_bonus_applied_once(self):
        members = [
            item("a", "gn-en-semi", source="Outlet A", company_ids=["nvidia"]),
            item("b", "gn-kr-semi", source="Outlet B", company_ids=["nvidia"]),
        ]
        self.assertEqual(score_cluster(members, TIERS), 3.0)


class CompanyMatchTest(unittest.TestCase):
    def setUp(self):
        self.compiled = compile_company_terms(COMPANIES)

    def test_ascii_terms_respect_alnum_boundaries(self):
        self.assertEqual(match_company_ids("Musk teases new chip", self.compiled), [])
        self.assertEqual(match_company_ids("amd64 build fixed", self.compiled), [])
        self.assertEqual(match_company_ids("nvidia ships Rubin", self.compiled), ["nvidia"])

    def test_tickers_match_case_sensitively(self):
        self.assertEqual(match_company_ids("(NASDAQ: MU) upgraded", self.compiled), ["micron"])
        self.assertEqual(match_company_ids("mu rises today", self.compiled), [])

    def test_hangul_exclusions_block_false_positives(self):
        self.assertEqual(match_company_ids("메타그린 신제품 출시", self.compiled), [])
        self.assertEqual(match_company_ids("메타버스 플랫폼 확대", self.compiled), [])
        self.assertEqual(match_company_ids("메타, 실적 발표", self.compiled), ["meta"])

    def test_ids_returned_in_companies_order(self):
        text = "Micron and NVIDIA sign HBM deal"
        self.assertEqual(match_company_ids(text, self.compiled), ["nvidia", "micron"])


class EnrichItemsTest(unittest.TestCase):
    def test_overwrites_stale_annotations(self):
        stale = item(
            "a", "thelec",
            cluster_id="stale", company_ids=["bogus"], score=99.0,
        )
        enriched = enrich_items([stale], TIERS, COMPANIES)[0]
        self.assertEqual(enriched["cluster_id"], "a")
        self.assertEqual(enriched["company_ids"], [])
        self.assertEqual(enriched["score"], 3.0)


if __name__ == "__main__":
    unittest.main()
