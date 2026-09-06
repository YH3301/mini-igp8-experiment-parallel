import csv
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from mini_igp8.storage import EXPERIMENT_FIELDS, Store, initial_state


class StorageTests(unittest.TestCase):
    def make_store(self, temporary):
        root = Path(temporary)
        (root / "data").mkdir()
        source = Path(__file__).resolve().parents[1] / "data" / "targets.json"
        shutil.copy2(source, root / "data" / "targets.json")
        store = Store(root)
        store.reset_results()
        return store

    def test_reset_is_a_true_empty_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = self.make_store(temporary)
            self.assertEqual(store.state(), initial_state())
            self.assertEqual(store.catalogue(), {})
            self.assertEqual(store.experiments(), [])
            self.assertEqual(store.seen_hashes(), set())
            self.assertEqual(store.history_file.read_text(), "")

    def test_catalogue_preserves_first_provenance_but_updates_best_discriminant(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = self.make_store(temporary)
            base = {
                "status": "verified",
                "galois_group": "8T44",
                "real_roots": 2,
                "coefficients": [1] + [0] * 7 + [1],
                "polynomial_discriminant": 100,
                "field_discriminant": 80,
            }
            first = store.update_catalogue([base], solver_commit="first", source_event="e1")
            self.assertEqual(first.new_pairs, ("8T44|2",))
            change = store.replace_best_if_smaller(
                "8T44|2",
                coefficients=[2] + [0] * 7 + [1],
                polynomial_discriminant=70,
                field_discriminant=50,
                solver_commit="best",
                source_event="e2",
            )
            self.assertTrue(change.improved)
            entry = store.catalogue()["8T44|2"]
            self.assertEqual(entry["first_solver_commit"], "first")
            self.assertEqual(entry["first_coefficients"][0], 1)
            self.assertEqual(entry["best_solver_commit"], "best")
            self.assertEqual(entry["field_discriminant"], 50)
            self.assertEqual(entry["coefficients"][0], 2)

    def test_worse_discriminant_does_not_replace_best(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = self.make_store(temporary)
            base = {
                "status": "verified", "galois_group": "8T44", "real_roots": 2,
                "coefficients": [1] + [0] * 7 + [1],
                "polynomial_discriminant": 100, "field_discriminant": 50,
            }
            store.update_catalogue([base], solver_commit="a", source_event="e1")
            change = store.replace_best_if_smaller(
                "8T44|2", coefficients=[3] + [0] * 7 + [1],
                polynomial_discriminant=60, field_discriminant=55,
                solver_commit="b", source_event="e2",
            )
            self.assertFalse(change.improved)
            self.assertEqual(store.catalogue()["8T44|2"]["coefficients"][0], 1)

    def test_experiments_and_history_are_append_only_across_report_rebuilds(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = self.make_store(temporary)
            for index in range(25):
                row = {field: "" for field in EXPERIMENT_FIELDS}
                row.update({
                    "generation": index,
                    "candidate_id": "A",
                    "timestamp": str(index),
                    "accepted": "yes" if index % 5 == 0 else "no",
                    "stage": "final",
                    "reason_code": "test",
                    "hypothesis": f"hypothesis-{index}",
                })
                store.append_experiment(row)
                store.append_history("test", {"index": index}, session_id="s")
                store.rebuild_report()
            self.assertEqual(len(store.experiments()), 25)
            self.assertEqual(len(store.history_file.read_text().splitlines()), 25)
            report = store.report_file.read_text()
            self.assertIn("hypothesis-0", report)
            self.assertIn("hypothesis-24", report)

    def test_seen_hashes_deduplicate_without_reread_and_are_bounded(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = self.make_store(temporary)
            known = set()
            self.assertEqual(store.add_seen_hashes(["a" * 32], known=known, max_entries=2), 1)
            self.assertEqual(store.add_seen_hashes(["a" * 32], known=known, max_entries=2), 0)
            self.assertEqual(store.add_seen_hashes(["b" * 32, "c" * 32], known=known, max_entries=2), 2)
            self.assertEqual(len(store.seen_hashes()), 2)
            self.assertIn("c" * 32, store.seen_hashes())

    def test_seen_hashes_reject_malformed_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = self.make_store(temporary)
            with self.assertRaisesRegex(ValueError, "new_seen_hash_contains_invalid_digest"):
                store.add_seen_hashes(["not-a-digest"])

    def test_experiment_header_is_exact(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = self.make_store(temporary)
            with store.experiments_file.open(newline="") as stream:
                self.assertEqual(csv.DictReader(stream).fieldnames, EXPERIMENT_FIELDS)


if __name__ == "__main__":
    unittest.main()
