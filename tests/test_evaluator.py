import tempfile
import unittest
from pathlib import Path

from mini_igp8.evaluator import (
    SOLVER_FILE,
    SolverError,
    call_solver,
    evaluate_fixed,
    evaluate_fresh,
    evaluate_search_batch,
    load_target_pairs,
    score_records,
    validate_solver_contract,
    validate_solver_source,
)


def verified(group="8T44", roots=2, coefficients=None):
    return {
        "status": "verified",
        "galois_group": group,
        "real_roots": roots,
        "coefficients": coefficients or [1] + [0] * 7 + [1],
        "polynomial_discriminant": 20,
    }


class EvaluatorTests(unittest.TestCase):
    def test_target_table(self):
        targets = load_target_pairs()
        self.assertEqual(len(targets), 157)
        self.assertEqual(len({group for group, _ in targets}), 50)

    def test_score_formula(self):
        records = [verified(), verified("8T39", 0), {"status": "reducible"}]
        score = score_records(records)
        self.assertAlmostEqual(score["score"], 2020 + 2 / 3)
        self.assertEqual(score["pairs"], 2)
        self.assertEqual(score["groups"], 2)

    def test_current_solver_contract_and_stress_generation(self):
        validate_solver_contract(SOLVER_FILE, stress_budget=1000)

    def test_nonreciprocal_and_large_coefficients_are_allowed(self):
        source = """
def generate_candidates(seed, budget):
    return [[i + 1, 10**40 + i, 0, 0, 0, 0, 0, 0, 1] for i in range(budget)]
"""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "solver.py"
            path.write_text(source)
            validate_solver_contract(path)

    def test_wrong_budget_is_specific(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "solver.py"
            path.write_text("def generate_candidates(seed,budget): return []\n")
            with self.assertRaisesRegex(SolverError, "solver_wrong_budget"):
                call_solver(path, seed=1, budget=2, timeout_seconds=5)

    def test_static_guard_blocks_effects_io_and_private_module_escape(self):
        with self.assertRaisesRegex(SolverError, "top_level_call"):
            validate_solver_source("x = print('bad')\ndef generate_candidates(seed,budget): return []")
        with self.assertRaisesRegex(SolverError, "name_forbidden:open"):
            validate_solver_source("def generate_candidates(seed,budget):\n open('x')\n return []")
        with self.assertRaisesRegex(SolverError, "private_attribute_forbidden:_os"):
            validate_solver_source(
                "import random\ndef generate_candidates(seed,budget):\n random._os.system('x')\n return []"
            )
        with self.assertRaisesRegex(SolverError, "private_import_forbidden"):
            validate_solver_source(
                "from random import _os as os\ndef generate_candidates(seed,budget):\n os.system('x')\n return []"
            )

    def test_fixed_benchmark_has_exact_slots(self):
        def fake(candidate, **_kwargs):
            return verified(coefficients=candidate)

        summary, records, _hashes = evaluate_fixed(
            SOLVER_FILE,
            seeds=(10, 20),
            candidates_per_seed=3,
            solver_seconds=5,
            verification_seconds=1,
            verifier=fake,
        )
        self.assertEqual(len(records), 6)
        self.assertEqual(summary["candidate_slots"], 6)

    def test_fresh_evaluation_tracks_consistency_by_seed(self):
        def fake(candidate, **_kwargs):
            return verified(coefficients=candidate)

        summary, records, _hashes = evaluate_fresh(
            SOLVER_FILE,
            seeds=(10, 20),
            candidates_per_seed=3,
            oversample_factor=1,
            catalogue_pairs=set(),
            already_seen=set(),
            solver_seconds=5,
            verification_seconds=1,
            verifier=fake,
        )
        self.assertEqual(len(records), 6)
        self.assertEqual(summary["fresh_new_pairs"], 1)
        self.assertEqual(summary["fresh_seed_count"], 2)
        self.assertEqual(summary["fresh_seed_hits"], 2)
        self.assertEqual(summary["fresh_pair_hits"], 2)
        self.assertEqual(set(summary["_fresh_seed_pair_counts"]), {10, 20})

    def test_search_only_marks_candidates_that_were_actually_verified(self):
        calls = []

        def fake(candidate, **_kwargs):
            calls.append(candidate)
            return verified(coefficients=candidate)

        summary, records, hashes = evaluate_search_batch(
            SOLVER_FILE,
            seed=1,
            budget=5,
            oversample_factor=2,
            already_seen=set(),
            solver_seconds=5,
            verification_seconds=1,
            verifier=fake,
        )
        self.assertEqual(summary["submitted"], 5)
        self.assertEqual(len(records), 5)
        self.assertEqual(len(hashes), 5)
        self.assertEqual(len(calls), 5)


if __name__ == "__main__":
    unittest.main()
