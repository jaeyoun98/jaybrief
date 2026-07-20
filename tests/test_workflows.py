import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PAGES_WORKFLOW = ROOT / ".github" / "workflows" / "pages.yml"


class PagesWorkflowTest(unittest.TestCase):
    def test_runtime_data_is_not_committed_to_main(self):
        workflow = PAGES_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("ref: runtime-data", workflow)
        self.assertIn("git commit-tree", workflow)
        self.assertIn("--force-with-lease=refs/heads/runtime-data", workflow)
        self.assertNotIn("Update feed data", workflow)
        self.assertNotIn("Update digest", workflow)

    def test_site_artifact_combines_shell_and_runtime_data(self):
        workflow = PAGES_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("cp -a runtime/data _site/data", workflow)
        self.assertIn("actions/upload-pages-artifact@v3", workflow)
        self.assertIn("actions/deploy-pages@v4", workflow)

    def test_legacy_data_workflows_are_removed(self):
        workflows = ROOT / ".github" / "workflows"
        self.assertFalse((workflows / "feed.yml").exists())
        self.assertFalse((workflows / "digest.yml").exists())


if __name__ == "__main__":
    unittest.main()
