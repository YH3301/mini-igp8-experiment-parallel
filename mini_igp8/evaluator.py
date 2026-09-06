"""Solver isolation, candidate selection, hidden evaluation, and scoring."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Callable, Iterable

from .verifier import validate_coefficients, verify


ROOT = Path(__file__).resolve().parents[1]
TARGETS_FILE = ROOT / "data" / "targets.json"
SOLVER_FILE = ROOT / "mini_igp8" / "solver.py"
BASELINE_SOLVER_FILE = ROOT / "mini_igp8" / "baseline_solver.py"

ALLOWED_IMPORTS = {
    "__future__", "bisect", "collections", "dataclasses", "fractions",
    "functools", "heapq", "itertools", "math", "operator", "random",
    "statistics", "typing",
}
FORBIDDEN_NAMES = {
    "open", "eval", "exec", "compile", "__import__", "input", "globals",
    "locals", "vars", "getattr", "setattr", "delattr", "breakpoint",
}
MAX_SOLVER_SOURCE_CHARS = 100_000


MAX_BATCHED_SOLVER_CANDIDATES = 2000


class SolverError(RuntimeError):
    """A solver failed a precisely identified interface requirement."""


class EvaluationDeadlineExceeded(RuntimeError):
    """A comparison could not finish before the session deadline."""


_SOLVER_RUNNER = r'''
import contextlib, importlib.util, io, json, pathlib, sys
path = pathlib.Path(sys.argv[1])
cases = json.loads(sys.argv[2])
spec = importlib.util.spec_from_file_location("candidate_solver", path)
if spec is None or spec.loader is None:
    raise RuntimeError("solver_import_spec_failed")
module = importlib.util.module_from_spec(spec)
results = []
with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    spec.loader.exec_module(module)
    for seed, budget in cases:
        results.append(module.generate_candidates(seed=int(seed), budget=int(budget)))
sys.stdout.write(json.dumps(results, separators=(",", ":")))
'''


def load_target_pairs(path: Path = TARGETS_FILE) -> frozenset[tuple[str, int]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    raw_pairs = data.get("pairs")
    raw_groups = data.get("groups")
    if not isinstance(raw_pairs, list) or not isinstance(raw_groups, list):
        raise ValueError("target_table_invalid_shape")

    try:
        pairs = frozenset(
            (entry["galois_group"], int(entry["real_roots"]))
            for entry in raw_pairs
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("target_table_invalid_pair_entry") from exc

    groups = {group for group, _ in pairs}
    expected_groups = {f"8T{index}" for index in range(1, 51)}
    if (
        data.get("degree") != 8
        or data.get("number_of_groups") != 50
        or data.get("number_of_pairs") != 157
        or len(raw_pairs) != 157
        or len(pairs) != 157
        or groups != expected_groups
        or len(raw_groups) != 50
    ):
        raise ValueError("target_table_not_degree_8_50_groups_157_pairs")
    if any(root not in {0, 2, 4, 6, 8} for _, root in pairs):
        raise ValueError("target_table_invalid_real_root_count")

    pair_roots = {group: set() for group in expected_groups}
    for group, roots in pairs:
        pair_roots[group].add(roots)
    seen_group_rows: set[str] = set()
    for entry in raw_groups:
        try:
            label = str(entry["label"])
            number = int(entry["transitive_number"])
            order = int(entry["group_order"])
            valid_roots = {int(value) for value in entry["valid_r"]}
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("target_table_invalid_group_entry") from exc
        if (
            label != f"8T{number}"
            or label not in expected_groups
            or label in seen_group_rows
            or order <= 0
            or valid_roots != pair_roots[label]
        ):
            raise ValueError(f"target_table_group_metadata_mismatch:{label}")
        seen_group_rows.add(label)
    if seen_group_rows != expected_groups:
        raise ValueError("target_table_group_metadata_incomplete")
    return pairs


def coefficient_hash(coefficients: Iterable[int]) -> str:
    payload = json.dumps(list(coefficients), separators=(",", ":")).encode("ascii")
    return hashlib.blake2b(payload, digest_size=16).hexdigest()


def solver_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_solver_source(
    source: str,
    *,
    known_polynomials: set[tuple[int, ...]] | None = None,
    held_out_seeds: set[int] | None = None,
) -> None:
    """Reject I/O, hidden-seed leakage, unsafe imports, and top-level effects."""

    if len(source) > MAX_SOLVER_SOURCE_CHARS:
        raise SolverError("solver_source_too_large")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise SolverError(f"solver_syntax_error:{exc.msg}") from exc

    functions = {
        statement.name for statement in tree.body
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    if "generate_candidates" not in functions:
        raise SolverError("solver_missing_generate_candidates")

    for statement in tree.body:
        allowed = isinstance(
            statement,
            (
                ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef,
                ast.ClassDef, ast.Assign, ast.AnnAssign, ast.Expr,
            ),
        )
        if not allowed:
            raise SolverError(f"solver_top_level_statement_forbidden:{type(statement).__name__}")
        if isinstance(statement, ast.Expr) and not (
            isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        ):
            raise SolverError("solver_top_level_expression_forbidden")
        if isinstance(statement, (ast.Assign, ast.AnnAssign)):
            value = statement.value
            if value is not None and any(isinstance(node, ast.Call) for node in ast.walk(value)):
                raise SolverError("solver_top_level_call_forbidden")

    known_polynomials = known_polynomials or set()
    held_out_seeds = held_out_seeds or set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                raise SolverError("solver_relative_import_forbidden")
            if any(alias.name.startswith("_") for alias in node.names):
                raise SolverError("solver_private_import_forbidden")
            modules = [node.module or ""]
        else:
            modules = []
        for module in modules:
            if module.split(".")[0] not in ALLOWED_IMPORTS:
                raise SolverError(f"solver_import_forbidden:{module}")

        if isinstance(node, ast.Name):
            if node.id in FORBIDDEN_NAMES or node.id.startswith("__"):
                raise SolverError(f"solver_name_forbidden:{node.id}")
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise SolverError(f"solver_private_attribute_forbidden:{node.attr}")
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, int)
            and not isinstance(node.value, bool)
            and node.value in held_out_seeds
        ):
            raise SolverError("solver_contains_held_out_seed")
        if isinstance(node, (ast.List, ast.Tuple)) and len(node.elts) == 9:
            values: list[int] = []
            for element in node.elts:
                if isinstance(element, ast.Constant) and type(element.value) is int:
                    values.append(element.value)
                elif (
                    isinstance(element, ast.UnaryOp)
                    and isinstance(element.op, ast.USub)
                    and isinstance(element.operand, ast.Constant)
                    and type(element.operand.value) is int
                ):
                    values.append(-element.operand.value)
                else:
                    break
            if len(values) == 9 and tuple(values) in known_polynomials:
                raise SolverError("solver_hardcodes_catalogue_polynomial")


def _remaining_timeout(timeout_seconds: int | float, deadline: float | None) -> float:
    if deadline is None:
        return float(timeout_seconds)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise EvaluationDeadlineExceeded("evaluation_deadline_reached")
    return max(0.05, min(float(timeout_seconds), remaining))


def _call_solver_cases(
    solver_path: Path,
    *,
    cases: list[tuple[int, int]],
    timeout_seconds: int | float,
    deadline: float | None = None,
) -> list[list[list[int]]]:
    """Run one solver module against several cases in one isolated interpreter.

    Batching contract probes avoids paying Python interpreter startup for every
    seed/budget pair. Normal search/evaluation still uses the same isolation
    boundary through :func:`call_solver`.
    """

    if not cases:
        return []
    solver_path = Path(solver_path).resolve()
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    timeout = _remaining_timeout(timeout_seconds, deadline)
    encoded_cases = json.dumps([[int(seed), int(budget)] for seed, budget in cases], separators=(",", ":"))
    with tempfile.TemporaryDirectory(prefix="mini-igp8-solver-") as temporary:
        try:
            completed = subprocess.run(
                [sys.executable, "-I", "-c", _SOLVER_RUNNER, str(solver_path), encoded_cases],
                cwd=temporary,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            if deadline is not None and time.monotonic() >= deadline:
                raise EvaluationDeadlineExceeded("evaluation_deadline_reached") from exc
            raise SolverError("solver_call_timeout") from exc
    if completed.returncode:
        detail = completed.stderr.strip().splitlines()[-1] if completed.stderr.strip() else "unknown"
        raise SolverError(f"solver_process_failed:{detail[:240]}")
    try:
        raw_batches = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SolverError("solver_output_not_json") from exc
    if not isinstance(raw_batches, list) or len(raw_batches) != len(cases):
        raise SolverError("solver_output_batch_shape_invalid")

    normalized_batches: list[list[list[int]]] = []
    for (_seed, budget), raw in zip(cases, raw_batches, strict=True):
        if not isinstance(raw, list):
            raise SolverError("solver_output_not_list")
        if len(raw) != budget:
            raise SolverError(f"solver_wrong_budget:expected={budget}:actual={len(raw)}")
        try:
            normalized = [validate_coefficients(candidate) for candidate in raw]
        except ValueError as exc:
            raise SolverError(f"solver_invalid_candidate:{exc}") from exc
        if len({tuple(candidate) for candidate in normalized}) != len(normalized):
            raise SolverError("solver_duplicate_within_call")
        normalized_batches.append(normalized)
    return normalized_batches


def call_solver(
    solver_path: Path,
    *,
    seed: int,
    budget: int,
    timeout_seconds: int | float,
    deadline: float | None = None,
) -> list[list[int]]:
    """Execute one solver call in a disposable isolated process."""

    return _call_solver_cases(
        solver_path,
        cases=[(seed, budget)],
        timeout_seconds=timeout_seconds,
        deadline=deadline,
    )[0]


def _call_solver_cases_chunked(
    solver_path: Path,
    *,
    cases: list[tuple[int, int]],
    timeout_seconds: int | float,
    deadline: float | None = None,
    max_candidates_per_process: int = MAX_BATCHED_SOLVER_CANDIDATES,
) -> list[list[list[int]]]:
    """Execute many logical solver calls without giving one giant batch one tiny timeout.

    ``solver_call_seconds`` is calibrated against roughly one normal search-sized
    generation (2,000 generated candidates by default).  Fresh races can contain
    dozens of seeds; sending all of them through one subprocess accidentally made
    the same timeout cover 4,000--12,000 generated candidates.  Chunking preserves
    interpreter amortization while keeping the timeout semantics comparable across
    screening, benchmarks, and larger race rounds.
    """

    if max_candidates_per_process <= 0:
        raise ValueError("max_candidates_per_process_must_be_positive")
    if not cases:
        return []

    outputs: list[list[list[int]]] = []
    chunk: list[tuple[int, int]] = []
    chunk_candidates = 0
    for case in cases:
        budget = int(case[1])
        if chunk and chunk_candidates + budget > max_candidates_per_process:
            outputs.extend(_call_solver_cases(
                solver_path, cases=chunk, timeout_seconds=timeout_seconds, deadline=deadline
            ))
            chunk = []
            chunk_candidates = 0
        chunk.append(case)
        chunk_candidates += budget
        if chunk_candidates >= max_candidates_per_process:
            outputs.extend(_call_solver_cases(
                solver_path, cases=chunk, timeout_seconds=timeout_seconds, deadline=deadline
            ))
            chunk = []
            chunk_candidates = 0
    if chunk:
        outputs.extend(_call_solver_cases(
            solver_path, cases=chunk, timeout_seconds=timeout_seconds, deadline=deadline
        ))
    return outputs


def validate_solver_contract(
    solver_path: Path,
    *,
    timeout_seconds: int | float = 30,
    known_polynomials: set[tuple[int, ...]] | None = None,
    held_out_seeds: set[int] | None = None,
    stress_budget: int | None = None,
) -> None:
    source = Path(solver_path).read_text(encoding="utf-8")
    validate_solver_source(
        source,
        known_polynomials=known_polynomials,
        held_out_seeds=held_out_seeds,
    )
    probes = [(1, 0), (1, 0), (1, 1), (1, 1), (2, 8), (2, 8),
              (3, 64), (3, 64), (4, 200), (4, 200)]
    if stress_budget is not None and stress_budget > 200:
        probes.append((8675309, int(stress_budget)))
    outputs = _call_solver_cases(
        solver_path, cases=probes, timeout_seconds=timeout_seconds,
    )
    for index in range(0, 10, 2):
        if outputs[index] != outputs[index + 1]:
            raise SolverError("solver_nondeterministic")


def _check_deadline(deadline: float | None) -> None:
    if deadline is not None and time.monotonic() >= deadline:
        raise EvaluationDeadlineExceeded("evaluation_deadline_reached")


def _maybe_progress(
    progress: Callable[[int, int], None] | None,
    done: int,
    total: int,
    every: int,
) -> None:
    if progress is not None and (done == total or done == 1 or (every > 0 and done % every == 0)):
        progress(done, total)


def score_records(records: list[dict]) -> dict:
    verified = [record for record in records if record.get("status") == "verified"]
    pairs = {(record["galois_group"], int(record["real_roots"])) for record in verified}
    invalid = pairs - load_target_pairs()
    if invalid:
        raise ValueError(f"verifier_returned_unknown_target:{sorted(invalid)}")
    groups = {group for group, _ in pairs}
    fraction = len(verified) / len(records) if records else 0.0
    return {
        "score": 1000.0 * len(pairs) + 10.0 * len(groups) + fraction,
        "pairs": len(pairs),
        "groups": len(groups),
        "verified": len(verified),
        "candidate_slots": len(records),
        "verified_fraction": fraction,
        "status_counts": dict(Counter(record.get("status", "missing") for record in records)),
        "pair_keys": sorted([list(pair) for pair in pairs], key=lambda item: (int(item[0][2:]), item[1])),
    }


def evaluate_fixed(
    solver_path: Path,
    *,
    seeds: Iterable[int],
    candidates_per_seed: int,
    solver_seconds: int | float,
    verification_seconds: int | float,
    verifier: Callable[..., dict] = verify,
    deadline: float | None = None,
    progress: Callable[[int, int], None] | None = None,
    progress_every: int = 0,
) -> tuple[dict, list[dict], set[str]]:
    seeds = tuple(int(seed) for seed in seeds)
    total = len(seeds) * candidates_per_seed
    records: list[dict] = []
    hashes: set[str] = set()
    started = time.monotonic()
    done = 0
    _check_deadline(deadline)
    batches = _call_solver_cases_chunked(
        solver_path,
        cases=[(seed, candidates_per_seed) for seed in seeds],
        timeout_seconds=solver_seconds,
        deadline=deadline,
    )
    for seed, candidates in zip(seeds, batches, strict=True):
        for index, candidate in enumerate(candidates):
            _check_deadline(deadline)
            digest = coefficient_hash(candidate)
            if digest in hashes:
                record = {
                    "status": "duplicate_candidate",
                    "coefficients": candidate,
                    "seed": seed,
                    "candidate_index": index,
                }
            else:
                hashes.add(digest)
                result = verifier(
                    candidate,
                    timeout_seconds=_remaining_timeout(verification_seconds, deadline),
                )
                record = {**result, "seed": seed, "candidate_index": index}
            records.append(record)
            done += 1
            _maybe_progress(progress, done, total, progress_every)
    summary = score_records(records)
    summary.update({
        "sage_calls": sum(record.get("status") != "duplicate_candidate" for record in records),
        "elapsed_seconds": time.monotonic() - started,
    })
    return summary, records, hashes


def _select_unseen(
    candidates: Iterable[list[int]],
    *,
    budget: int,
    already_seen: set[str],
) -> list[list[int]]:
    selected: list[list[int]] = []
    selected_hashes: set[str] = set()
    for candidate in candidates:
        digest = coefficient_hash(candidate)
        if digest in already_seen or digest in selected_hashes:
            continue
        selected.append(candidate)
        selected_hashes.add(digest)
        if len(selected) == budget:
            break
    return selected


def evaluate_search_batch(
    solver_path: Path,
    *,
    seed: int,
    budget: int,
    oversample_factor: int,
    already_seen: set[str],
    solver_seconds: int | float,
    verification_seconds: int | float,
    verifier: Callable[..., dict] = verify,
    deadline: float | None = None,
    progress: Callable[[int, int], None] | None = None,
    progress_every: int = 0,
) -> tuple[dict, list[dict], set[str]]:
    _check_deadline(deadline)
    raw = call_solver(
        solver_path,
        seed=seed,
        budget=budget * oversample_factor,
        timeout_seconds=solver_seconds,
        deadline=deadline,
    )
    candidates = _select_unseen(raw, budget=budget, already_seen=already_seen)
    started = time.monotonic()
    records: list[dict] = []
    processed_hashes: set[str] = set()
    deadline_reached = False
    total = len(candidates)
    for index, candidate in enumerate(candidates, 1):
        if deadline is not None and time.monotonic() >= deadline:
            deadline_reached = True
            break
        record = verifier(
            candidate,
            timeout_seconds=_remaining_timeout(verification_seconds, deadline),
        )
        records.append(record)
        processed_hashes.add(coefficient_hash(candidate))
        _maybe_progress(progress, index, total, progress_every)
    summary = score_records(records)
    summary.update({
        "requested": budget,
        "selected": len(candidates),
        "submitted": len(records),
        "sage_calls": len(records),
        "deadline_reached": deadline_reached,
        "elapsed_seconds": time.monotonic() - started,
    })
    return summary, records, processed_hashes


def summarize_fresh_records(
    records: list[dict],
    *,
    catalogue_pairs: set[tuple[str, int]],
) -> dict:
    """Summarize fresh paired-race evidence without exposing hidden seed values.

    ``fresh_new_pairs`` measures distinct currently-missing target pairs across
    the complete sample. ``fresh_seed_hits`` and ``fresh_pair_hits`` measure
    consistency across independent seeds. ``_fresh_seed_pair_counts`` is an
    internal mapping used only for paired comparisons and is stripped before
    evidence is persisted or shown to an AI agent.
    """

    summary = score_records(records)
    pairs = {tuple(pair) for pair in summary["pair_keys"]}
    marginal = pairs - catalogue_pairs
    seed_pair_sets: dict[int, set[tuple[str, int]]] = {}
    for record in records:
        seed = record.get("seed")
        if seed is None:
            continue
        seed_pair_sets.setdefault(int(seed), set())
        if record.get("status") != "verified":
            continue
        pair = (record["galois_group"], int(record["real_roots"]))
        if pair not in catalogue_pairs:
            seed_pair_sets[int(seed)].add(pair)
    seed_counts = {seed: len(found) for seed, found in seed_pair_sets.items()}
    summary.update({
        "fresh_new_pairs": len(marginal),
        "fresh_new_pair_keys": sorted(
            [list(pair) for pair in marginal], key=lambda item: (int(item[0][2:]), item[1])
        ),
        "fresh_seed_count": len(seed_counts),
        "fresh_seed_hits": sum(count > 0 for count in seed_counts.values()),
        "fresh_pair_hits": sum(seed_counts.values()),
        "_fresh_seed_pair_counts": seed_counts,
        "sage_calls": sum(record.get("status") != "no_unseen_candidate" for record in records),
    })
    return summary


def evaluate_fresh(
    solver_path: Path,
    *,
    seeds: Iterable[int],
    candidates_per_seed: int,
    oversample_factor: int,
    catalogue_pairs: set[tuple[str, int]],
    already_seen: set[str],
    solver_seconds: int | float,
    verification_seconds: int | float,
    verifier: Callable[..., dict] = verify,
    deadline: float | None = None,
    progress: Callable[[int, int], None] | None = None,
    progress_every: int = 0,
) -> tuple[dict, list[dict], set[str]]:
    seeds = tuple(int(seed) for seed in seeds)
    total = len(seeds) * candidates_per_seed
    records: list[dict] = []
    hashes: set[str] = set()
    started = time.monotonic()
    variant_seen = set(already_seen)
    done = 0
    _check_deadline(deadline)
    batches = _call_solver_cases_chunked(
        solver_path,
        cases=[(seed, candidates_per_seed * oversample_factor) for seed in seeds],
        timeout_seconds=solver_seconds,
        deadline=deadline,
    )
    for seed, raw in zip(seeds, batches, strict=True):
        candidates = _select_unseen(raw, budget=candidates_per_seed, already_seen=variant_seen)
        selected_hashes = {coefficient_hash(candidate) for candidate in candidates}
        variant_seen.update(selected_hashes)
        hashes.update(selected_hashes)
        for index, candidate in enumerate(candidates):
            _check_deadline(deadline)
            result = verifier(
                candidate,
                timeout_seconds=_remaining_timeout(verification_seconds, deadline),
            )
            records.append({**result, "seed": seed, "candidate_index": index})
            done += 1
            _maybe_progress(progress, done, total, progress_every)
        missing = candidates_per_seed - len(candidates)
        for index in range(len(candidates), candidates_per_seed):
            records.append({
                "status": "no_unseen_candidate",
                "seed": seed,
                "candidate_index": index,
            })
            done += 1
            _maybe_progress(progress, done, total, progress_every)
    summary = summarize_fresh_records(records, catalogue_pairs=catalogue_pairs)
    summary["elapsed_seconds"] = time.monotonic() - started
    return summary, records, hashes
