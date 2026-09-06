"""Durable append-only state for one Mini-IGP8 experiment run."""

from __future__ import annotations

import csv
import json
import os
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .evaluator import load_target_pairs


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
RESULT_FILENAMES = (
    "catalogue.jsonl",
    "experiments.csv",
    "history.jsonl",
    "report.md",
    "seen_hashes.txt",
    "state.json",
)

EXPERIMENT_FIELDS = [
    "generation", "candidate_id", "timestamp", "accepted", "stage", "reason_code",
    "label", "hypothesis",
    "screen_score", "screen_missing_pairs",
    "benchmark_score", "benchmark_pairs",
    "fresh_missing_pairs", "fresh_seed_hits", "fresh_pair_hits", "fresh_race_seeds",
    "discriminant_improvements", "best_discriminant_ratio",
    "catalogue_pairs_before", "catalogue_pairs_after", "catalogue_groups_after",
    "verified_fraction", "sage_calls", "ai_calls",
    "input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens",
    "solver_commit", "solver_hash", "session_id",
]


class GitError(RuntimeError):
    """A required local Git operation failed."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def atomic_json(path: Path, value: object) -> None:
    atomic_text(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def git(*arguments: str, root: Path = ROOT) -> str | None:
    result = subprocess.run(
        ["git", *arguments], cwd=root, capture_output=True, text=True, check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def commit_paths(root: Path, message: str, paths: Iterable[str]) -> str | None:
    """Commit selected paths using a repository-local automation identity."""

    root = Path(root)
    selected = list(paths)
    add = subprocess.run(
        ["git", "add", "--", *selected], cwd=root, capture_output=True, text=True, check=False,
    )
    if add.returncode:
        raise GitError(f"git_add_failed:{add.stderr.strip()[:300]}")
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=root).returncode == 0:
        return None
    completed = subprocess.run(
        [
            "git", "-c", "user.name=Mini-IGP8", "-c",
            "user.email=mini-igp8@invalid.local", "commit", "-m", message,
            "--", *selected,
        ],
        cwd=root, capture_output=True, text=True, check=False,
    )
    if completed.returncode:
        raise GitError(f"git_commit_failed:{completed.stderr.strip()[:300]}")
    head = git("rev-parse", "HEAD", root=root)
    if not head:
        raise GitError("git_commit_missing_head")
    return head


def initial_state() -> dict:
    return {
        "version": 5,
        "run_id": None,
        "next_generation": 0,
        "next_search_batch": 0,
        "search_candidates_total": 0,
        "last_new_pair_at": 0,
        "last_solver_change_at": 0,
        "generation_feedback": None,
        "accepted_solver_commit": None,
        "incumbent_solver_hash": None,
        "incumbent_benchmark": None,
        "discriminant_improvements_total": 0,
        "last_stop_code": "not_started",
    }


@dataclass(frozen=True)
class CatalogueChange:
    new_pairs: tuple[str, ...]


@dataclass(frozen=True)
class DiscriminantChange:
    improved: bool
    pair_key: str
    old_value: int | None
    new_value: int


class Store:
    """Read and update the complete durable state for the current run."""

    def __init__(self, root: Path = ROOT):
        self.root = Path(root)
        self.results = self.root / "results"
        self.catalogue_file = self.results / "catalogue.jsonl"
        self.experiments_file = self.results / "experiments.csv"
        self.history_file = self.results / "history.jsonl"
        self.seen_file = self.results / "seen_hashes.txt"
        self.state_file = self.results / "state.json"
        self.report_file = self.results / "report.md"

    def reset_results(self) -> None:
        """Return results to a true empty-run state."""

        self.results.mkdir(parents=True, exist_ok=True)
        atomic_text(self.catalogue_file, "")
        atomic_text(self.history_file, "")
        atomic_text(self.seen_file, "")
        with self.experiments_file.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=EXPERIMENT_FIELDS, lineterminator="\n")
            writer.writeheader()
            stream.flush()
            os.fsync(stream.fileno())
        atomic_json(self.state_file, initial_state())
        self.rebuild_report()

    def state(self) -> dict:
        value = json.loads(self.state_file.read_text(encoding="utf-8"))
        if value.get("version") != 5:
            raise ValueError("state_version_not_5")
        missing = sorted(set(initial_state()) - set(value))
        if missing:
            raise ValueError(f"state_missing_fields:{missing}")
        return value

    def save_state(self, state: dict) -> None:
        if state.get("version") != 5:
            raise ValueError("state_version_not_5")
        atomic_json(self.state_file, state)

    @staticmethod
    def pair_key(group: str, roots: int) -> str:
        return f"{group}|{roots}"

    @staticmethod
    def _catalogue_sort(entry: dict) -> tuple[int, int]:
        return int(entry["galois_group"][2:]), int(entry["real_roots"])

    def catalogue(self) -> dict[str, dict]:
        entries: dict[str, dict] = {}
        if not self.catalogue_file.exists():
            return entries
        for number, line in enumerate(self.catalogue_file.read_text(encoding="utf-8").splitlines(), 1):
            if not line:
                continue
            entry = json.loads(line)
            key = self.pair_key(entry["galois_group"], int(entry["real_roots"]))
            if key in entries:
                raise ValueError(f"duplicate_catalogue_pair:line={number}:key={key}")
            entries[key] = entry
        unknown = {
            (entry["galois_group"], int(entry["real_roots"]))
            for entry in entries.values()
        } - load_target_pairs(self.root / "data" / "targets.json")
        if unknown:
            raise ValueError(f"catalogue_unknown_target:{sorted(unknown)}")
        return entries

    def write_catalogue(self, entries: dict[str, dict]) -> None:
        lines = [
            json.dumps(entry, sort_keys=True)
            for entry in sorted(entries.values(), key=self._catalogue_sort)
        ]
        atomic_text(self.catalogue_file, "\n".join(lines) + ("\n" if lines else ""))

    def update_catalogue(
        self,
        records: Iterable[dict],
        *,
        solver_commit: str | None,
        source_event: str,
    ) -> CatalogueChange:
        """Add first verified representatives only; hidden evaluation never calls this."""

        entries = self.catalogue()
        targets = load_target_pairs(self.root / "data" / "targets.json")
        new: list[str] = []
        for record in records:
            if record.get("status") != "verified":
                continue
            pair = (record["galois_group"], int(record["real_roots"]))
            if pair not in targets:
                raise ValueError(f"catalogue_update_unknown_target:{pair}")
            key = self.pair_key(*pair)
            if key in entries:
                continue
            stamp = now()
            entry = {
                "galois_group": pair[0],
                "real_roots": pair[1],
                "coefficients": list(record["coefficients"]),
                "field_discriminant": record.get("field_discriminant"),
                "polynomial_discriminant": int(record["polynomial_discriminant"]),
                "first_coefficients": list(record["coefficients"]),
                "first_field_discriminant": record.get("field_discriminant"),
                "first_polynomial_discriminant": int(record["polynomial_discriminant"]),
                "first_discovered_at": stamp,
                "first_solver_commit": solver_commit,
                "first_source_event": source_event,
                "best_updated_at": stamp,
                "best_solver_commit": solver_commit,
                "best_source_event": source_event,
            }
            entries[key] = entry
            new.append(key)
        if new:
            self.write_catalogue(entries)
        return CatalogueChange(tuple(sorted(new)))

    def set_new_pair_field_discriminant(self, pair_key: str, value: int) -> None:
        entries = self.catalogue()
        if pair_key not in entries:
            raise KeyError(pair_key)
        entries[pair_key]["field_discriminant"] = int(value)
        if entries[pair_key].get("first_field_discriminant") is None:
            entries[pair_key]["first_field_discriminant"] = int(value)
        self.write_catalogue(entries)

    def replace_best_if_smaller(
        self,
        pair_key: str,
        *,
        coefficients: list[int],
        polynomial_discriminant: int,
        field_discriminant: int,
        solver_commit: str | None,
        source_event: str,
    ) -> DiscriminantChange:
        """Replace only the best representative; preserve first-discovery provenance."""

        entries = self.catalogue()
        if pair_key not in entries:
            raise KeyError(pair_key)
        entry = entries[pair_key]
        old = entry.get("field_discriminant")
        new = int(field_discriminant)
        if old is not None and new >= int(old):
            return DiscriminantChange(False, pair_key, int(old), new)

        entry["coefficients"] = list(coefficients)
        entry["polynomial_discriminant"] = int(polynomial_discriminant)
        entry["field_discriminant"] = new
        entry["best_updated_at"] = now()
        entry["best_solver_commit"] = solver_commit
        entry["best_source_event"] = source_event
        self.write_catalogue(entries)
        return DiscriminantChange(True, pair_key, None if old is None else int(old), new)

    def seen_hashes(self) -> set[str]:
        if not self.seen_file.exists():
            return set()
        values = {
            line.strip() for line in self.seen_file.read_text(encoding="ascii").splitlines()
            if line.strip()
        }
        if any(
            len(value) != 32 or any(character not in "0123456789abcdef" for character in value)
            for value in values
        ):
            raise ValueError("seen_hash_file_contains_invalid_digest")
        return values

    @staticmethod
    def _validate_hashes(values: Iterable[str], code: str) -> set[str]:
        result = set(values)
        if any(
            len(value) != 32 or any(character not in "0123456789abcdef" for character in value)
            for value in result
        ):
            raise ValueError(code)
        return result

    def add_seen_hashes(
        self,
        hashes: Iterable[str],
        *,
        known: set[str] | None = None,
        max_entries: int | None = None,
    ) -> int:
        """Maintain only the rolling duplicate-protection window, never experiment history."""

        incoming = self._validate_hashes(hashes, "new_seen_hash_contains_invalid_digest")
        current = self.seen_hashes() if known is None else known
        new = sorted(incoming - current)
        if not new:
            return 0
        if max_entries is not None and max_entries <= 0:
            raise ValueError("seen_hash_limit_not_positive")

        if max_entries is not None and len(current) + len(new) > max_entries:
            old_order = [
                line.strip() for line in self.seen_file.read_text(encoding="ascii").splitlines()
                if line.strip()
            ]
            order: list[str] = []
            present: set[str] = set()
            for value in [*old_order, *new]:
                if value not in present:
                    present.add(value)
                    order.append(value)
            keep = order[-max_entries:]
            atomic_text(self.seen_file, "\n".join(keep) + ("\n" if keep else ""))
            current.clear()
            current.update(keep)
        else:
            with self.seen_file.open("a", encoding="ascii") as stream:
                for value in new:
                    stream.write(value + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            current.update(new)
        return len(new)

    def append_history(self, event: str, details: dict, *, session_id: str) -> str:
        """Append one immutable history event. This file is never truncated during a run."""

        event_id = uuid.uuid4().hex[:12]
        record = {
            "event_id": event_id,
            "timestamp": now(),
            "session_id": session_id,
            "event": event,
            "details": details,
        }
        with self.history_file.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        return event_id

    def experiments(self) -> list[dict]:
        if not self.experiments_file.exists():
            return []
        with self.experiments_file.open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames != EXPERIMENT_FIELDS:
                raise ValueError("experiments_csv_header_mismatch")
            return [{field: row.get(field) or "" for field in EXPERIMENT_FIELDS} for row in reader]

    def append_experiment(self, row: dict) -> None:
        """Append one row. Accepted solvers never delete or rewrite earlier rows."""

        missing = [field for field in EXPERIMENT_FIELDS if field not in row]
        extra = [field for field in row if field not in EXPERIMENT_FIELDS]
        if missing or extra:
            raise ValueError(f"experiment_schema_mismatch:missing={missing}:extra={extra}")
        exists = self.experiments_file.exists()
        with self.experiments_file.open("a", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=EXPERIMENT_FIELDS, lineterminator="\n")
            if not exists:
                writer.writeheader()
            writer.writerow(row)
            stream.flush()
            os.fsync(stream.fileno())

    def known_polynomials(self) -> set[tuple[int, ...]]:
        return {tuple(entry["coefficients"]) for entry in self.catalogue().values()}

    def rebuild_report(self) -> None:
        catalogue = self.catalogue()
        state = self.state()
        experiments = self.experiments()
        pairs = len(catalogue)
        groups = len({entry["galois_group"] for entry in catalogue.values()})
        accepted = sum(row["accepted"] == "yes" and row["stage"] == "final" for row in experiments)
        benchmark = state.get("incumbent_benchmark") or {}
        score = benchmark.get("score", "not measured")
        anchor = max(state["last_new_pair_at"], state["last_solver_change_at"])
        since_progress = state["search_candidates_total"] - anchor
        lines = [
            "# Mini-IGP8 status", "",
            f"- Run: **{state.get('run_id') or 'not started'}**",
            f"- Catalogue: **{pairs} / 157 pairs** across **{groups} / 50 groups**",
            f"- Current frozen-benchmark score: **{score}**",
            f"- Search candidates checked: **{state['search_candidates_total']}**",
            f"- Search candidates since new pair/solver change: **{since_progress}**",
            f"- Accepted solver generations: **{accepted}**",
            f"- Best-field-discriminant improvements: **{state['discriminant_improvements_total']}**",
            f"- Last stop: `{state.get('last_stop_code', 'not_started')}`", "",
            "## Complete solver experiment history", "",
            "This table is intentionally append-only. Earlier rows are never hidden or deleted when a solver is accepted.", "",
            "| Gen | Candidate | Accepted | Stage | Screen | Benchmark | Fresh pairs | Seed hits | Disc improvements | Reason | Hypothesis |",
            "|---:|---|---|---|---:|---:|---:|---:|---:|---|---|",
        ]
        for row in experiments:
            hypothesis = row["hypothesis"].replace("|", "\\|").replace("\n", " ")
            lines.append(
                f"| {row['generation']} | {row['candidate_id']} | {row['accepted']} | {row['stage']} | "
                f"{row['screen_score']} | {row['benchmark_score']} | {row['fresh_missing_pairs']} | "
                f"{row['fresh_seed_hits']} | {row['discriminant_improvements']} | "
                f"`{row['reason_code']}` | {hypothesis} |"
            )
        lines.extend([
            "", "## Catalogue", "",
            "| Group | r | Field discriminant | First solver | Best solver | Coefficients |",
            "|---|---:|---:|---|---|---|",
        ])
        for entry in sorted(catalogue.values(), key=self._catalogue_sort):
            coefficients = ", ".join(map(str, entry["coefficients"]))
            field_disc = entry.get("field_discriminant")
            first = (entry.get("first_solver_commit") or "-")[:12]
            best = (entry.get("best_solver_commit") or "-")[:12]
            lines.append(
                f"| {entry['galois_group']} | {entry['real_roots']} | "
                f"{field_disc if field_disc is not None else '-'} | `{first}` | `{best}` | `{coefficients}` |"
            )
        atomic_text(self.report_file, "\n".join(lines) + "\n")
