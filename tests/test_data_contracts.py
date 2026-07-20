import json
import unittest
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class EventDataContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.companies = json.loads((ROOT / "companies.json").read_text(encoding="utf-8"))["companies"]
        cls.events = json.loads((ROOT / "events.json").read_text(encoding="utf-8"))["events"]

    def test_company_and_event_ids_are_unique(self):
        company_ids = [company["id"] for company in self.companies]
        event_ids = [event["id"] for event in self.events]
        self.assertEqual(len(company_ids), len(set(company_ids)))
        self.assertEqual(len(event_ids), len(set(event_ids)))

    def test_events_reference_known_companies_and_valid_values(self):
        company_ids = {company["id"] for company in self.companies}
        for event in self.events:
            with self.subTest(event=event["id"]):
                self.assertIn(event["type"], {"earnings", "conference", "macro"})
                self.assertIn(event["status"], {"confirmed", "estimated", "detected"})
                self.assertTrue(set(event["company_ids"]).issubset(company_ids))
                self.assertTrue(event["source_url"].startswith("https://"))
                self.assertIn(event["importance"], {1, 2, 3})
                datetime.fromisoformat(event["start_at"])
                if event.get("end_at"):
                    datetime.fromisoformat(event["end_at"])


if __name__ == "__main__":
    unittest.main()
