import unittest

from mini_igp8.storage import RESULT_FILENAMES, ROOT


class LayoutTests(unittest.TestCase):
    def test_repository_layout_is_fixed_and_small(self):
        allowed = {
            ".git", ".gitignore", ".idea", ".pytest_cache", ".ruff_cache",
            ".venv", ".vscode", "AGENTS.md", "README.md", "build",
            "candidates", "config.toml", "data", "dist", "environment.yml",
            "mini_igp8", "pyproject.toml", "results", "tests",
        }
        unexpected = sorted(
            path.name for path in ROOT.iterdir()
            if path.name not in allowed and not path.name.endswith(".egg-info")
            and path.name != ".mini-igp8-research.lock"
        )
        self.assertEqual(unexpected, [], "new root entries require explicit human approval")

    def test_results_are_exactly_six_stable_files(self):
        actual = {path.name for path in (ROOT / "results").iterdir() if not path.name.endswith(".tmp")}
        self.assertEqual(actual, set(RESULT_FILENAMES))
        self.assertTrue(all(path.is_file() for path in (ROOT / "results").iterdir()))

    def test_candidate_workspace_is_bounded_and_ignored(self):
        candidates = ROOT / "candidates"
        self.assertTrue((candidates / "README.md").is_file())
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("/candidates/current/", ignore)
        self.assertFalse((candidates / "current").exists())

    def test_package_and_tests_remain_flat(self):
        for directory in (ROOT / "mini_igp8", ROOT / "tests"):
            subdirectories = {
                path.name for path in directory.iterdir()
                if path.is_dir() and path.name != "__pycache__"
            }
            self.assertEqual(subdirectories, set())

    def test_no_unbounded_run_or_agent_artifact_directories(self):
        for name in ("runs", "campaigns", "automation", "worktrees", "proposals"):
            self.assertFalse((ROOT / name).exists())


if __name__ == "__main__":
    unittest.main()
