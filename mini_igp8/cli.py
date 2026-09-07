"""Beginner-facing commands: check, status, research, and new-run/reset."""

from __future__ import annotations

import argparse
import fcntl
import json
import shutil
import subprocess
import sys

from .codex import CodexFailure, ensure_codex
from .evaluator import (
    BASELINE_SOLVER_FILE,
    SOLVER_FILE,
    load_target_pairs,
    validate_solver_contract,
)
from .research import ResearchController, ResearchStop, load_config, research_lock_path
from .storage import RESULT_FILENAMES, ROOT, GitError, Store, commit_paths, git
from .verifier import SageUnavailableError, ensure_sage_available


def run_tests() -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return False, "test suite exceeded 120 seconds"
    return completed.returncode == 0, (completed.stdout + completed.stderr).strip()


def check(_args: argparse.Namespace) -> int:
    store = Store()
    checks: list[tuple[str, bool, str]] = []
    try:
        config = load_config()
        checks.append((
            "configuration",
            True,
            f"{config.batch_size} search candidates/batch; AI after {config.stagnation} stagnant; "
            f"1 Sol -> {config.candidate_count} parallel Terra candidates; "
            f"{config.verification_workers} Sage workers; Sage calls uncapped; "
            f"{config.max_ai} AI calls/session",
        ))
    except Exception as exc:
        config = None
        checks.append(("configuration", False, str(exc)))
    try:
        targets = load_target_pairs()
        checks.append(("target table", len(targets) == 157, "157 pairs / 50 groups"))
    except Exception as exc:
        checks.append(("target table", False, str(exc)))
    try:
        catalogue = store.catalogue()
        checks.append(("catalogue", True, f"{len(catalogue)} current-run pairs"))
    except Exception as exc:
        catalogue = {}
        checks.append(("catalogue", False, str(exc)))
    try:
        validate_solver_contract(
            SOLVER_FILE,
            timeout_seconds=config.solver_seconds if config else 30,
            known_polynomials={tuple(entry["coefficients"]) for entry in catalogue.values()},
            held_out_seeds=(
                set(config.benchmark_seeds) | set(config.screening_seeds)
                if config else set()
            ),
            stress_budget=2000,
        )
        checks.append(("solver", True, "deterministic, isolated, unique, and fast enough"))
    except Exception as exc:
        checks.append(("solver", False, str(exc)))
    try:
        state = store.state()
        clean = state["run_id"] is None
        if clean and SOLVER_FILE.read_bytes().replace(b"\r\n", b"\n") != BASELINE_SOLVER_FILE.read_bytes().replace(b"\r\n", b"\n"):
            raise ValueError("not_started_state_but_solver_is_not_baseline")
        checks.append((
            "research state",
            True,
            "clean slate" if clean else f"run {state['run_id']} ready to resume",
        ))
    except Exception as exc:
        checks.append(("research state", False, str(exc)))
    try:
        ensure_sage_available()
        checks.append(("SageMath", True, "available"))
    except SageUnavailableError as exc:
        checks.append(("SageMath", False, str(exc)))
    try:
        ensure_codex()
        checks.append(("Codex CLI", True, "installed and current"))
    except CodexFailure as exc:
        checks.append(("Codex CLI", False, str(exc)))
    passed, output = run_tests()
    checks.append(("tests", passed, "all passed" if passed else "\n".join(output.splitlines()[-10:])))
    git_ok = git("rev-parse", "--is-inside-work-tree") == "true"
    checks.append(("Git", git_ok, git("rev-parse", "--short", "HEAD") or "not initialized"))

    width = max(len(name) for name, _, _ in checks)
    for name, ok, detail in checks:
        print(f"[{'OK' if ok else 'FAIL':4}] {name:<{width}}  {detail}")
    failures = [name for name, ok, _ in checks if not ok]
    if failures:
        print("\nNot ready: " + ", ".join(failures))
        return 1
    print("\nReady. Run: mini-igp8 research")
    return 0


def status(args: argparse.Namespace) -> int:
    snapshot = ResearchController().snapshot()
    if args.json:
        print(json.dumps(snapshot, indent=2, sort_keys=True))
    else:
        print(f"Run             {snapshot['run_id'] or 'not started'}")
        print(f"Catalogue       {snapshot['catalogue_pairs']} / 157 pairs")
        print(f"Groups          {snapshot['catalogue_groups']} / 50")
        print(f"Search checked  {snapshot['search_candidates_total']}")
        print(f"Recent hashes   {snapshot['recent_seen_candidates']}")
        print(f"Since progress  {snapshot['candidates_since_discovery_or_solver_change']}")
        print(f"Next generation {snapshot['next_generation']}")
        print(f"Disc improved   {snapshot['discriminant_improvements_total']}")
        print(f"Last stop       {snapshot['last_stop_code']}")
        print("Readable report results/report.md")
    return 0


def research(args: argparse.Namespace) -> int:
    progress = (lambda _message: None) if args.quiet else (
        lambda message: print(f"[mini-igp8] {message}", file=sys.stderr, flush=True)
    )
    try:
        result = ResearchController(progress=progress).run(dry_run=args.dry_run)
    except (ResearchStop, SageUnavailableError, ValueError, OSError) as exc:
        print(f"research stopped safely: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def reset(args: argparse.Namespace) -> int:
    if not args.yes:
        print(
            "Refusing to erase the current experiment without --yes. "
            "This resets solver.py and all six results files.",
            file=sys.stderr,
        )
        return 2
    if git("rev-parse", "--is-inside-work-tree") != "true":
        print("reset requires the repository's local Git history", file=sys.stderr)
        return 2
    lock_path = research_lock_path(ROOT)
    with lock_path.open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("cannot start a new run while research is active", file=sys.stderr)
            return 2
        shutil.rmtree(ROOT / "candidates" / "current", ignore_errors=True)
        shutil.copyfile(BASELINE_SOLVER_FILE, SOLVER_FILE)
        store = Store()
        store.reset_results()
        try:
            commit = commit_paths(
                ROOT,
                "research: reset to clean slate",
                ["mini_igp8/solver.py", *[f"results/{name}" for name in RESULT_FILENAMES]],
            )
        except GitError as exc:
            print(f"reset files written but Git checkpoint failed: {exc}", file=sys.stderr)
            return 2
    print("Reset complete: empty catalogue/history, naive baseline solver, no active run.")
    if commit:
        print(f"Reset commit: {commit[:12]}")
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="mini-igp8", description="Mini-IGP8 autonomous research")
    commands = root.add_subparsers(dest="command", required=True)

    command = commands.add_parser("check", help="verify setup and invariants")
    command.set_defaults(function=check)

    command = commands.add_parser("status", help="show current-run progress")
    command.add_argument("--json", action="store_true")
    command.set_defaults(function=status)

    command = commands.add_parser("research", help="start or resume the current run")
    command.add_argument("--dry-run", action="store_true")
    command.add_argument("--quiet", action="store_true", help="suppress live progress messages")
    command.set_defaults(function=research)

    command = commands.add_parser("new-run", aliases=["reset"], help="erase current-run evidence and restore the naive solver")
    command.add_argument("--yes", action="store_true", help="confirm destructive reset")
    command.set_defaults(function=reset)
    return root


def main(arguments: list[str] | None = None) -> int:
    args = parser().parse_args(arguments)
    return int(args.function(args))


if __name__ == "__main__":
    raise SystemExit(main())
