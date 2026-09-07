import unittest

from mini_igp8.storage import RESULT_FILENAMES, ROOT


class LayoutTests(unittest.TestCase):
    def test_repository_root_stays_small(self):
        allowed = {
            ".git", ".gitignore", ".idea", ".pytest_cache", ".ruff_cache",
            ".venv", ".vscode", "AGENTS.md", "README.md", "build",
            "candidates", "config.toml", "data", "dist", "environment.yml",
            "mini_igp8", "pyproject.toml", "results", "tests",
        }
        unexpected = sorted(
            path.name for path in ROOT.iterdir()
            if path.name not in allowed
            and not path.name.endswith(".egg-info")
            and path.name != ".mini-igp8-research.lock"
        )
        self.assertEqual(unexpected, [])

    def test_results_use_the_fixed_files(self):
        actual = {
            path.name for path in (ROOT / "results").iterdir()
            if not path.name.endswith(".tmp")
        }
        self.assertEqual(actual, set(RESULT_FILENAMES))

    def test_persistent_candidate_workspace_is_git_ignored(self):
        self.assertTrue((ROOT / "candidates" / "README.md").is_file())
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("/candidates/current/", ignore)


if __name__ == "__main__":
    unittest.main()
