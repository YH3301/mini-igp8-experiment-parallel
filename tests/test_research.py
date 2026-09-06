import json
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from mini_igp8.codex import CodexResponse, TokenUsage
from mini_igp8.evaluator import BASELINE_SOLVER_FILE, SOLVER_FILE, solver_sha256
from mini_igp8.research import (
    Budget,
    ResearchController,
    _research_prompt,
    acceptance_decision,
    load_config,
    paired_race_metrics,
    race_checkpoint_decision,
    screening_decision,
)
from mini_igp8.storage import ROOT, Store


def benchmark(score, *, pairs=1, verified=3):
    return {
        "score": score,
        "pairs": pairs,
        "groups": 1,
        "verified": verified,
        "candidate_slots": 3,
        "verified_fraction": verified / 3,
        "status_counts": {"verified": verified},
        "sage_calls": 3,
    }


def race_fresh(counts, *, distinct=None):
    values = list(counts)
    return {
        "fresh_new_pairs": max(values, default=0) if distinct is None else distinct,
        "fresh_seed_hits": sum(value > 0 for value in values),
        "fresh_pair_hits": sum(values),
        "fresh_seed_count": len(values),
        "_fresh_seed_pair_counts": {index + 1: value for index, value in enumerate(values)},
    }


def hypothesis(candidate_id):
    return {
        "candidate_id": candidate_id,
        "label": f"candidate-{candidate_id}",
        "mission": f"distinct mission {candidate_id}",
        "hypothesis": f"{candidate_id} structured family",
        "rationale": "exercise a distinct construction",
        "implementation": "replace or extend the generator",
        "expected_result": "more missing target-pair coverage",
        "falsification_test": "reject if measured evidence is weak",
    }


TEST_CONFIG = """
version = 5
[search]
master_seed = 9
batch_size = 1
oversample_factor = 2
ask_ai_after_stagnation = 1
recent_hash_limit = 100
[generation]
candidate_count = 5
parallel_implementers = 5
max_screen_survivors = 3
max_synthesis_finalists = 3
[screening]
seeds = [101]
candidates_per_seed = 3
[benchmark]
seeds = [102]
candidates_per_seed = 3
[comparison]
master_seed = 10
round_seed_counts = [1, 1, 1]
candidates_per_seed = 3
oversample_factor = 1
[final_comparison]
master_seed = 11
round_seed_counts = [1, 1]
candidates_per_seed = 3
oversample_factor = 1
max_challengers_after_round1 = 2
[discriminants]
continue_after_full_coverage = true
max_checks_per_search_batch = 1
max_checks_per_finalist = 1
[limits]
max_ai_calls_per_session = {max_ai}
max_wall_minutes_per_session = 1
ai_call_seconds = 5
solver_call_seconds = 5
verification_seconds = 1
progress_every_candidates = 100
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


class FakeLLM:
    def __init__(self):
        self.lock = threading.Lock()
        self.research_calls = 0
        self.implementation_calls = 0
        self.synthesis_calls = 0
        self.critic_calls = 0

    def call(self, *, cwd, schema=None, prompt="", **_kwargs):
        usage = TokenUsage(input_tokens=10, output_tokens=2)
        if schema is not None:
            properties = schema.get("properties", {})
            if "generation_thesis" in properties:
                with self.lock:
                    self.research_calls += 1
                data = {
                    "generation_thesis": "five orthogonal attacks",
                    "hypotheses": [hypothesis(letter) for letter in "ABCDE"],
                }
                return CodexResponse(json.dumps(data), data, usage)
            if "implementation_plan" in properties:
                with self.lock:
                    self.synthesis_calls += 1
                data = {
                    "thesis": "combine the strongest complementary families",
                    "components": ["best rare-group family", "robust fallback"],
                    "implementation_plan": "use a deterministic budget split",
                    "budget_allocation": "70/30",
                    "risks": ["budget dilution"],
                }
                return CodexResponse(json.dumps(data), data, usage)
            if "next_generation_direction" in properties:
                with self.lock:
                    self.critic_calls += 1
                data = {
                    "diagnosis": "generation-level diagnosis",
                    "what_worked": ["diverse families"],
                    "avoid": ["duplicate mechanisms"],
                    "next_generation_direction": "attack uncovered groups",
                }
                return CodexResponse(json.dumps(data), data, usage)

        name = Path(cwd).name
        marker_map = {
            "candidate-A": 1001,
            "candidate-B": 1002,
            "candidate-C": 1003,
            "candidate-D": 1004,
            "candidate-E": 1005,
            "candidate-S": 1099,
        }
        marker = marker_map[name]
        with self.lock:
            self.implementation_calls += 1
        Path(cwd, "solver.py").write_text(
            "def generate_candidates(seed, budget):\n"
            f"    return [[i + 1, {marker}, 0, 0, 0, 0, 0, 0, 1] for i in range(budget)]\n",
            encoding="utf-8",
        )
        return CodexResponse("implemented", None, usage)


def fake_verifier(candidate, **_kwargs):
    marker = candidate[1]
    if marker == 1001:
        return {"status": "reducible", "coefficients": candidate, "polynomial_discriminant": 100}
    roots_by_marker = {
        1002: (0, 2),
        1003: (0, 4),
        1004: (0, 6),
        1005: (0, 8),
        1099: (2, 4, 6, 8),
    }
    roots_options = roots_by_marker.get(marker, (0,))
    roots = roots_options[(abs(candidate[0]) - 1) % len(roots_options)]
    return {
        "status": "verified",
        "coefficients": candidate,
        "galois_group": "8T50",
        "real_roots": roots,
        "field_discriminant": max(1, 1000 - abs(marker) - abs(candidate[0])),
        "polynomial_discriminant": 2000 + abs(marker) + abs(candidate[0]),
    }


def fake_field_discriminant(candidate, **_kwargs):
    return max(1, 1000 - abs(candidate[1]) - abs(candidate[0]))


def make_temp_repo(temporary, *, max_ai=9):
    root = Path(temporary)
    shutil.copytree(ROOT / "mini_igp8", root / "mini_igp8")
    shutil.copytree(ROOT / "data", root / "data")
    shutil.copytree(ROOT / "candidates", root / "candidates")
    shutil.copy2(ROOT / ".gitignore", root / ".gitignore")
    # Synthetic test repos must always begin from the canonical baseline, even
    # if the real live experiment has already evolved solver.py.
    shutil.copy2(root / "mini_igp8" / "baseline_solver.py", root / "mini_igp8" / "solver.py")
    (root / "config.toml").write_text(TEST_CONFIG.format(max_ai=max_ai), encoding="utf-8")
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
    def test_acceptance_is_missing_pairs_then_discriminant_then_benchmark(self):
        incumbent = race_fresh([0, 0], distinct=0)
        better_missing = race_fresh([1, 0], distinct=1)
        self.assertTrue(acceptance_decision(benchmark(100), benchmark(1), incumbent, better_missing)[0])

        tied = race_fresh([0, 0], distinct=0)
        self.assertTrue(acceptance_decision(
            benchmark(100), benchmark(1), tied, tied,
            {"improvements": 0, "best_ratio": 1.0},
            {"improvements": 1, "best_ratio": 0.5},
        )[0])
        self.assertTrue(acceptance_decision(
            benchmark(100), benchmark(110), tied, tied,
            {"improvements": 0, "best_ratio": 1.0},
            {"improvements": 0, "best_ratio": 1.0},
        )[0])

    def test_adaptive_race_requires_more_than_one_round_before_accepting(self):
        incumbent = race_fresh([0] * 10, distinct=0)
        challenger = race_fresh([1] * 5 + [0] * 5, distinct=3)
        action, _ = race_checkpoint_decision(
            benchmark(100), benchmark(100), incumbent, challenger,
            round_index=0, total_rounds=3,
        )
        self.assertEqual(action, "continue")

    def test_adaptive_race_can_accept_clear_round2_gain(self):
        incumbent = race_fresh([0] * 30, distinct=0)
        challenger = race_fresh([1] * 8 + [0] * 22, distinct=3)
        metrics = paired_race_metrics(incumbent, challenger)
        self.assertEqual(metrics["proposal_seed_wins"], 8)
        action, reason = race_checkpoint_decision(
            benchmark(100), benchmark(100), incumbent, challenger,
            round_index=1, total_rounds=3,
        )
        self.assertEqual((action, reason), ("accept", "accepted_clear_round2_gain"))

    def test_screening_only_rejects_no_verified_candidates(self):
        self.assertTrue(screening_decision(benchmark(1, pairs=0, verified=1))[0])
        self.assertFalse(screening_decision(benchmark(100, verified=0))[0])

    def test_default_configuration_is_parallel_generation_based(self):
        config = load_config()
        self.assertEqual(config.stagnation, 5000)
        self.assertEqual(config.candidate_count, 5)
        self.assertEqual(config.parallel_implementers, 5)
        self.assertEqual(config.max_screen_survivors, 3)
        self.assertEqual(config.screening_slots, 500)
        self.assertEqual(config.benchmark_slots, 2000)
        self.assertEqual(config.fresh_round_seed_counts, (10, 20, 30))
        self.assertEqual(config.final_round_seed_counts, (20, 40))
        self.assertGreaterEqual(config.max_ai, 2)
        self.assertFalse(hasattr(config, "max_sage"))
        self.assertEqual(config.researcher_model, "gpt-5.6-sol")
        self.assertEqual(config.implementer_model, "gpt-5.6-terra")
        self.assertEqual(config.synthesizer_model, "gpt-5.6-sol")
        self.assertEqual(config.critic_model, "gpt-5.6-sol")

    def test_sage_calls_are_telemetry_not_a_budget(self):
        budget = Budget(load_config(), time.monotonic())
        budget.spend_sage(10**9)
        self.assertEqual(budget.sage, 10**9)

    def test_research_context_requests_five_distinct_hypotheses_and_hides_seeds(self):
        config = load_config()
        prompt = _research_prompt(Store(), Store().state(), config)
        self.assertIn("EXACTLY five", prompt)
        self.assertIn("Secondary objective", prompt)
        self.assertIn('"coverage_by_group"', prompt)
        for seed in (*config.benchmark_seeds, *config.screening_seeds):
            self.assertNotIn(str(seed), prompt)

    def test_clean_state_rejects_nonbaseline_solver(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = make_temp_repo(temporary, max_ai=0)
            (root / "mini_igp8" / "solver.py").write_text(
                "def generate_candidates(seed, budget):\n"
                "    return [[i + 1, 7, 0, 0, 0, 0, 0, 0, 1] for i in range(budget)]\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(Exception, "clean_slate_invariant_failed"):
                ResearchController(root=root, run_tests=lambda _root: None).run(dry_run=True)

    def test_temp_repo_helper_never_inherits_live_evolved_solver(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = make_temp_repo(temporary)
            self.assertEqual(
                (root / "mini_igp8" / "solver.py").read_bytes(),
                (root / "mini_igp8" / "baseline_solver.py").read_bytes(),
            )

    def test_generation_uses_one_researcher_five_terra_and_always_criticizes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = make_temp_repo(temporary, max_ai=9)
            llm = FakeLLM()
            messages = []
            with (
                patch("mini_igp8.research.ensure_sage_available"),
                patch("mini_igp8.research.ensure_codex"),
            ):
                controller = ResearchController(
                    root=root,
                    llm=llm,
                    verifier=fake_verifier,
                    field_discriminant_fn=fake_field_discriminant,
                    run_tests=lambda _root: None,
                    progress=messages.append,
                )
                # Contract execution is covered independently in test_evaluator;
                # keep this orchestration test focused and fast.
                controller._validate_solver = lambda _path: None
                result = controller.run()

            self.assertEqual(llm.research_calls, 1)
            self.assertEqual(llm.implementation_calls, 6)  # five candidates + one synthesis
            self.assertEqual(llm.synthesis_calls, 1)
            self.assertEqual(llm.critic_calls, 1)
            self.assertFalse((root / "candidates" / "current").exists())
            self.assertIn(result["last_stop_code"], {
                "ai_budget_insufficient_for_generation", "solver_produced_no_unseen_candidates"
            })
            events = [json.loads(line)["event"] for line in Store(root).history_file.read_text().splitlines()]
            self.assertIn("generation_completed", events)
            self.assertIn("generation_critic", events)

    def test_second_session_resumes_same_run_and_does_not_remeasure_baseline(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = make_temp_repo(temporary, max_ai=0)
            with patch("mini_igp8.research.ensure_sage_available"):
                first = ResearchController(
                    root=root, llm=FakeLLM(), verifier=fake_verifier,
                    field_discriminant_fn=fake_field_discriminant,
                    run_tests=lambda _root: None,
                ).run()
            first_state = Store(root).state()
            baseline_count = sum(
                json.loads(line)["event"] == "baseline_measured"
                for line in Store(root).history_file.read_text().splitlines()
            )
            with patch("mini_igp8.research.ensure_sage_available"):
                second = ResearchController(
                    root=root, llm=FakeLLM(), verifier=fake_verifier,
                    field_discriminant_fn=fake_field_discriminant,
                    run_tests=lambda _root: None,
                ).run()
            self.assertEqual(Store(root).state()["run_id"], first_state["run_id"])
            self.assertEqual(baseline_count, 1)
            self.assertEqual(sum(
                json.loads(line)["event"] == "baseline_measured"
                for line in Store(root).history_file.read_text().splitlines()
            ), 1)
            self.assertGreaterEqual(second["search_candidates_total"], first["search_candidates_total"])


    def test_normal_search_can_improve_known_field_discriminant_without_resetting_plateau(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = make_temp_repo(temporary, max_ai=0)
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
                verifier=fake_verifier,
                field_discriminant_fn=fake_field_discriminant,
                run_tests=lambda _root: None,
            )
            budget = Budget(controller.config, time.monotonic())
            records = [{
                "status": "verified",
                "galois_group": "8T44",
                "real_roots": 2,
                "coefficients": [1, 1005, 0, 0, 0, 0, 0, 0, 1],
                "polynomial_discriminant": 500,
                "field_discriminant": 100,
            }]
            improved = controller._improve_known_discriminants(
                records,
                excluded_new_pairs=set(),
                solver_commit="later",
                source_event="e2",
                state=state,
                budget=budget,
                session_id="s",
            )
            self.assertEqual(improved, 1)
            self.assertEqual(store.catalogue()["8T44|2"]["field_discriminant"], 100)
            self.assertEqual(state["last_new_pair_at"], 400)
            self.assertEqual(state["discriminant_improvements_total"], 1)

    def test_live_clean_state_is_truly_empty(self):
        store = Store()
        state = store.state()
        if state["run_id"] is None:
            self.assertEqual(state["search_candidates_total"], 0)
            self.assertEqual(state["next_generation"], 0)
            self.assertEqual(store.experiments(), [])
            self.assertEqual(store.catalogue(), {})
            self.assertEqual(store.seen_hashes(), set())
            self.assertEqual(SOLVER_FILE.read_bytes(), BASELINE_SOLVER_FILE.read_bytes())


if __name__ == "__main__":
    unittest.main()
