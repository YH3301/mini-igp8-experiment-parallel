import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from mini_igp8.codex import TokenUsage
from mini_igp8.research import (
    Budget,
    ResearchController,
    _initialize_workspace,
    acceptance_decision,
    load_config,
    paired_race_metrics,
    screening_decision,
)
from mini_igp8.storage import ROOT, Store


TEST_CONFIG = """
version = 6
[search]
master_seed = 9
batch_size = 10
oversample_factor = 1
ask_ai_after_stagnation = 50
recent_hash_limit = 100
[generation]
candidate_count = 5
parallel_implementers = 5
max_screen_survivors = 3
max_synthesis_finalists = 2
[screening]
seeds = [101]
candidates_per_seed = 3
[benchmark]
seeds = [102]
candidates_per_seed = 3
[comparison]
master_seed = 10
round_seed_counts = [1, 1]
candidates_per_seed = 3
oversample_factor = 1
[final_comparison]
master_seed = 11
round_seed_counts = [1, 1]
candidates_per_seed = 3
oversample_factor = 1
max_challengers_after_round1 = 1
[discriminants]
continue_after_full_coverage = true
max_checks_per_search_batch = 1
[limits]
max_ai_calls_per_session = 9
max_wall_minutes_per_session = 1
ai_call_seconds = 5
solver_call_seconds = 5
search_solver_call_seconds = 10
verification_seconds = 1
verification_workers = 1
progress_every_candidates = 10
[models]
researcher = "researcher"
researcher_reasoning = "high"
implementer = "implementer"
implementer_reasoning = "medium"
synthesizer = "synthesizer"
synthesizer_reasoning = "high"
critic = "critic"
critic_reasoning = "high"
"""


def fresh(counts, *, distinct=None):
    values = list(counts)
    return {
        "fresh_new_pairs": max(values, default=0) if distinct is None else distinct,
        "fresh_seed_hits": sum(value > 0 for value in values),
        "fresh_pair_hits": sum(values),
        "fresh_seed_count": len(values),
        "_fresh_seed_pair_counts": {index + 1: value for index, value in enumerate(values)},
    }


def make_temp_repo(temporary: str) -> Path:
    root = Path(temporary)
    shutil.copytree(ROOT / "mini_igp8", root / "mini_igp8")
    shutil.copytree(ROOT / "data", root / "data")
    shutil.copytree(ROOT / "candidates", root / "candidates")
    shutil.copy2(ROOT / ".gitignore", root / ".gitignore")
    shutil.copy2(root / "mini_igp8" / "baseline_solver.py", root / "mini_igp8" / "solver.py")
    (root / "config.toml").write_text(TEST_CONFIG, encoding="utf-8")
    Store(root).reset_results()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "initial"],
        cwd=root,
        check=True,
    )
    return root


class ResearchTests(unittest.TestCase):
    def test_default_configuration_matches_fast_generation_design(self):
        config = load_config()
        self.assertEqual(config.batch_size, 10_000)
        self.assertEqual(config.search_oversample, 1)
        self.assertEqual(config.stagnation, 50_000)
        self.assertEqual(config.candidate_count, 5)
        self.assertEqual(config.max_screen_survivors, 3)
        self.assertEqual(config.max_synthesis_finalists, 3)
        self.assertEqual(config.fresh_round_seed_counts, (5, 10))
        self.assertEqual(config.final_round_seed_counts, (20, 40))
        self.assertEqual(config.final_max_challengers_after_round1, 1)
        self.assertEqual(config.verification_workers, 4)
        self.assertEqual(config.max_ai, 45) # 5 iterations
        self.assertFalse(hasattr(config, "max_sage"))

    def test_screening_is_only_a_viability_gate(self):
        self.assertEqual(screening_decision({"verified": 0})[0], False)
        self.assertEqual(screening_decision({"verified": 1})[0], True)

    def test_paired_metrics_require_same_seed_horizon(self):
        with self.assertRaisesRegex(ValueError, "fresh_comparison_seed_mismatch"):
            paired_race_metrics(fresh([1, 0]), fresh([1]))

    def test_final_acceptance_prioritizes_missing_pairs(self):
        incumbent = fresh([1, 1], distinct=1)
        challenger = fresh([1, 0], distinct=2)
        accepted, reason = acceptance_decision(
            {"score": 50_000}, {"score": 1}, incumbent, challenger
        )
        self.assertTrue(accepted)
        self.assertEqual(reason, "accepted_discovery_gain")

    def test_benchmark_is_only_final_tiebreaker(self):
        evidence = fresh([1, 0], distinct=1)
        accepted, reason = acceptance_decision(
            {"score": 100}, {"score": 101}, evidence, evidence
        )
        self.assertTrue(accepted)
        self.assertEqual(reason, "accepted_benchmark_gain")

    def test_candidate_workspace_preserves_existing_solver(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "candidate-A"
            _initialize_workspace(path, "def generate_candidates(seed, budget):\n    return []\n", "first")
            original = "def generate_candidates(seed, budget):\n    return [[1,0,0,0,0,0,0,0,1]] * budget\n"
            (path / "solver.py").write_text(original, encoding="utf-8")
            subprocess.run(["git", "add", "solver.py"], cwd=path, check=True)
            subprocess.run(["git", "commit", "-qm", "lineage"], cwd=path, check=True)
            _initialize_workspace(path, "SHOULD NOT REPLACE", "second")
            self.assertEqual((path / "solver.py").read_text(encoding="utf-8"), original)

    def test_clean_state_rejects_nonbaseline_solver(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = make_temp_repo(temporary)
            (root / "mini_igp8" / "solver.py").write_text(
                "def generate_candidates(seed, budget):\n    return []\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(Exception, "clean_slate_invariant_failed"):
                ResearchController(root=root).run(dry_run=True)

    def test_sage_accounting_is_telemetry_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = make_temp_repo(temporary)
            controller = ResearchController(root=root)
            budget = Budget(controller.config, time.monotonic())
            budget.spend_sage(10_000_000)
            self.assertEqual(budget.sage, 10_000_000)
            self.assertGreater(budget.seconds_left, 0)

    def test_known_discriminant_improvement_does_not_reset_plateau(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = make_temp_repo(temporary)
            store = Store(root)
            store.update_catalogue([{
                "status": "verified",
                "galois_group": "8T44",
                "real_roots": 2,
                "coefficients": [10] + [0] * 7 + [1],
                "polynomial_discriminant": 1000,
                "field_discriminant": 800,
            }], solver_commit="first", source_event="e1")
            state = store.state()
            state["search_candidates_total"] = 500
            state["last_new_pair_at"] = 400
            store.save_state(state)
            controller = ResearchController(
                root=root,
                field_discriminant_fn=lambda *_args, **_kwargs: 100,
            )
            budget = Budget(controller.config, time.monotonic())
            improved = controller._improve_known_discriminants(
                [{
                    "status": "verified",
                    "galois_group": "8T44",
                    "real_roots": 2,
                    "coefficients": [1, 1005, 0, 0, 0, 0, 0, 0, 1],
                    "polynomial_discriminant": 500,
                }],
                excluded_new_pairs=set(),
                solver_commit="later",
                source_event="e2",
                state=state,
                budget=budget,
                session_id="s",
            )
            self.assertEqual(improved, 1)
            self.assertEqual(state["last_new_pair_at"], 400)
            self.assertEqual(store.catalogue()["8T44|2"]["field_discriminant"], 100)


if __name__ == "__main__":
    unittest.main()
