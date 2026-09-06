"""Parallel generation-based autonomous research loop for Mini-IGP8."""

from __future__ import annotations

import fcntl
import hashlib
import json
import shutil
import subprocess
import sys
import time
import tomllib
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .codex import CodexClient, CodexFailure, TokenUsage, ensure_codex
from .evaluator import (
    EvaluationDeadlineExceeded,
    SolverError,
    evaluate_fixed,
    evaluate_fresh,
    evaluate_search_batch,
    load_target_pairs,
    solver_sha256,
    summarize_fresh_records,
    validate_solver_contract,
)
from .storage import (
    EXPERIMENT_FIELDS,
    RESULT_FILENAMES,
    ROOT,
    GitError,
    Store,
    atomic_text,
    commit_paths,
    git,
    initial_state,
    now,
)
from .verifier import (
    VerificationTimeoutError,
    ensure_sage_available,
    field_discriminant,
    verify,
)


CONFIG_FILE = ROOT / "config.toml"

HYPOTHESIS_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "candidate_id": {"type": "string", "enum": ["A", "B", "C", "D", "E"]},
        "label": {"type": "string", "minLength": 1},
        "mission": {"type": "string", "minLength": 1},
        "hypothesis": {"type": "string", "minLength": 1},
        "rationale": {"type": "string", "minLength": 1},
        "implementation": {"type": "string", "minLength": 1},
        "expected_result": {"type": "string", "minLength": 1},
        "falsification_test": {"type": "string", "minLength": 1},
    },
    "required": [
        "candidate_id", "label", "mission", "hypothesis", "rationale",
        "implementation", "expected_result", "falsification_test",
    ],
    "additionalProperties": False,
}

RESEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "generation_thesis": {"type": "string", "minLength": 1},
        "hypotheses": {
            "type": "array",
            "minItems": 5,
            "maxItems": 5,
            "items": HYPOTHESIS_ITEM_SCHEMA,
        },
    },
    "required": ["generation_thesis", "hypotheses"],
    "additionalProperties": False,
}

SYNTHESIS_SCHEMA = {
    "type": "object",
    "properties": {
        "thesis": {"type": "string", "minLength": 1},
        "components": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "implementation_plan": {"type": "string", "minLength": 1},
        "budget_allocation": {"type": "string", "minLength": 1},
        "risks": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["thesis", "components", "implementation_plan", "budget_allocation", "risks"],
    "additionalProperties": False,
}

CRITIC_SCHEMA = {
    "type": "object",
    "properties": {
        "diagnosis": {"type": "string", "minLength": 1},
        "what_worked": {"type": "array", "items": {"type": "string"}},
        "avoid": {"type": "array", "items": {"type": "string"}},
        "next_generation_direction": {"type": "string", "minLength": 1},
    },
    "required": ["diagnosis", "what_worked", "avoid", "next_generation_direction"],
    "additionalProperties": False,
}


class ResearchStop(RuntimeError):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}:{detail}" if detail else code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class Config:
    search_master_seed: int
    batch_size: int
    search_oversample: int
    stagnation: int
    recent_hash_limit: int
    candidate_count: int
    parallel_implementers: int
    max_screen_survivors: int
    max_synthesis_finalists: int
    screening_seeds: tuple[int, ...]
    screening_size: int
    benchmark_seeds: tuple[int, ...]
    benchmark_size: int
    comparison_master_seed: int
    fresh_round_seed_counts: tuple[int, ...]
    fresh_size: int
    fresh_oversample: int
    final_master_seed: int
    final_round_seed_counts: tuple[int, ...]
    final_size: int
    final_oversample: int
    final_max_challengers_after_round1: int
    continue_after_full_coverage: bool
    discriminant_checks_per_batch: int
    discriminant_checks_per_finalist: int
    max_ai: int
    max_seconds: int
    ai_seconds: int
    solver_seconds: int
    verification_seconds: int
    progress_every: int
    researcher_model: str
    researcher_reasoning: str
    implementer_model: str
    implementer_reasoning: str
    synthesizer_model: str
    synthesizer_reasoning: str
    critic_model: str
    critic_reasoning: str

    @property
    def screening_slots(self) -> int:
        return len(self.screening_seeds) * self.screening_size

    @property
    def benchmark_slots(self) -> int:
        return len(self.benchmark_seeds) * self.benchmark_size

    @property
    def preliminary_slots_per_solver(self) -> int:
        return sum(self.fresh_round_seed_counts) * self.fresh_size

    @property
    def final_slots_per_solver(self) -> int:
        return sum(self.final_round_seed_counts) * self.final_size

    @property
    def minimum_generation_ai_calls(self) -> int:
        # researcher + all Terra candidates + end-of-generation critic
        return 1 + self.candidate_count + 1

    @property
    def full_generation_ai_calls(self) -> int:
        # plus Sol synthesis + Terra synthesis implementation
        return self.minimum_generation_ai_calls + 2


def _positive(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"config_not_positive_integer:{name}")
    return value


def _nonnegative(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"config_not_nonnegative_integer:{name}")
    return value


def _seed_tuple(values: object, name: str) -> tuple[int, ...]:
    if not isinstance(values, list) or not values:
        raise ValueError(f"config_invalid_seeds:{name}")
    seeds = tuple(values)
    if len(set(seeds)) != len(seeds) or any(type(seed) is not int or seed <= 0 for seed in seeds):
        raise ValueError(f"config_invalid_seeds:{name}")
    return seeds


def _positive_tuple(values: object, name: str) -> tuple[int, ...]:
    if not isinstance(values, list) or not values:
        raise ValueError(f"config_invalid_positive_list:{name}")
    result = tuple(values)
    if any(type(value) is not int or value <= 0 for value in result):
        raise ValueError(f"config_invalid_positive_list:{name}")
    return result


def load_config(path: Path = CONFIG_FILE) -> Config:
    with path.open("rb") as stream:
        raw = tomllib.load(stream)
    if raw.get("version") != 5:
        raise ValueError("config_version_not_5")
    search = raw["search"]
    generation = raw["generation"]
    screening = raw["screening"]
    benchmark = raw["benchmark"]
    comparison = raw["comparison"]
    final = raw["final_comparison"]
    discriminants = raw["discriminants"]
    limits = raw["limits"]
    models = raw["models"]

    efforts = {"low", "medium", "high", "xhigh"}
    for key in (
        "researcher_reasoning", "implementer_reasoning", "synthesizer_reasoning", "critic_reasoning"
    ):
        if models[key] not in efforts:
            raise ValueError(f"config_invalid_reasoning:{key}")

    screening_seeds = _seed_tuple(screening["seeds"], "screening.seeds")
    benchmark_seeds = _seed_tuple(benchmark["seeds"], "benchmark.seeds")
    if set(screening_seeds) & set(benchmark_seeds):
        raise ValueError("config_screening_benchmark_seed_overlap")

    candidate_count = _positive(generation["candidate_count"], "generation.candidate_count")
    if candidate_count != 5:
        raise ValueError("generation_candidate_count_must_be_5")
    max_screen = _positive(generation["max_screen_survivors"], "generation.max_screen_survivors")
    if max_screen > candidate_count:
        raise ValueError("generation_too_many_screen_survivors")
    max_synthesis = _positive(
        generation["max_synthesis_finalists"], "generation.max_synthesis_finalists"
    )
    if max_synthesis > max_screen:
        raise ValueError("generation_too_many_synthesis_finalists")

    max_ai = _nonnegative(limits["max_ai_calls_per_session"], "limits.max_ai_calls_per_session")
    return Config(
        search_master_seed=_positive(search["master_seed"], "search.master_seed"),
        batch_size=_positive(search["batch_size"], "search.batch_size"),
        search_oversample=_positive(search["oversample_factor"], "search.oversample_factor"),
        stagnation=_positive(search["ask_ai_after_stagnation"], "search.ask_ai_after_stagnation"),
        recent_hash_limit=_positive(search["recent_hash_limit"], "search.recent_hash_limit"),
        candidate_count=candidate_count,
        parallel_implementers=_positive(
            generation["parallel_implementers"], "generation.parallel_implementers"
        ),
        max_screen_survivors=max_screen,
        max_synthesis_finalists=max_synthesis,
        screening_seeds=screening_seeds,
        screening_size=_positive(screening["candidates_per_seed"], "screening.candidates_per_seed"),
        benchmark_seeds=benchmark_seeds,
        benchmark_size=_positive(benchmark["candidates_per_seed"], "benchmark.candidates_per_seed"),
        comparison_master_seed=_positive(comparison["master_seed"], "comparison.master_seed"),
        fresh_round_seed_counts=_positive_tuple(
            comparison["round_seed_counts"], "comparison.round_seed_counts"
        ),
        fresh_size=_positive(comparison["candidates_per_seed"], "comparison.candidates_per_seed"),
        fresh_oversample=_positive(comparison["oversample_factor"], "comparison.oversample_factor"),
        final_master_seed=_positive(final["master_seed"], "final_comparison.master_seed"),
        final_round_seed_counts=_positive_tuple(
            final["round_seed_counts"], "final_comparison.round_seed_counts"
        ),
        final_size=_positive(final["candidates_per_seed"], "final_comparison.candidates_per_seed"),
        final_oversample=_positive(final["oversample_factor"], "final_comparison.oversample_factor"),
        final_max_challengers_after_round1=_positive(
            final["max_challengers_after_round1"],
            "final_comparison.max_challengers_after_round1",
        ),
        continue_after_full_coverage=bool(discriminants["continue_after_full_coverage"]),
        discriminant_checks_per_batch=_nonnegative(
            discriminants["max_checks_per_search_batch"],
            "discriminants.max_checks_per_search_batch",
        ),
        discriminant_checks_per_finalist=_nonnegative(
            discriminants["max_checks_per_finalist"],
            "discriminants.max_checks_per_finalist",
        ),
        max_ai=max_ai,
        max_seconds=60 * _positive(
            limits["max_wall_minutes_per_session"], "limits.max_wall_minutes_per_session"
        ),
        ai_seconds=_positive(limits["ai_call_seconds"], "limits.ai_call_seconds"),
        solver_seconds=_positive(limits["solver_call_seconds"], "limits.solver_call_seconds"),
        verification_seconds=_positive(
            limits["verification_seconds"], "limits.verification_seconds"
        ),
        progress_every=_positive(
            limits["progress_every_candidates"], "limits.progress_every_candidates"
        ),
        researcher_model=str(models["researcher"]),
        researcher_reasoning=str(models["researcher_reasoning"]),
        implementer_model=str(models["implementer"]),
        implementer_reasoning=str(models["implementer_reasoning"]),
        synthesizer_model=str(models["synthesizer"]),
        synthesizer_reasoning=str(models["synthesizer_reasoning"]),
        critic_model=str(models["critic"]),
        critic_reasoning=str(models["critic_reasoning"]),
    )


@dataclass
class Budget:
    config: Config
    started: float
    sage: int = 0
    ai: int = 0
    usage: TokenUsage = TokenUsage()

    @property
    def ai_left(self) -> int:
        return max(0, self.config.max_ai - self.ai)

    @property
    def seconds_left(self) -> float:
        return max(0.0, self.config.max_seconds - (time.monotonic() - self.started))

    @property
    def deadline(self) -> float:
        return self.started + self.config.max_seconds

    def spend_sage(self, value: int) -> None:
        if value < 0:
            raise ResearchStop("sage_accounting_error", str(value))
        self.sage += value

    def reserve_ai(self, count: int = 1) -> None:
        if count < 0:
            raise ResearchStop("ai_accounting_error", str(count))
        if self.seconds_left <= 0:
            raise ResearchStop("wall_time_limit_reached")
        if self.ai_left < count:
            raise ResearchStop("ai_budget_exhausted", f"needed={count}:left={self.ai_left}")
        self.ai += count

    def add_usage(self, usage: TokenUsage) -> None:
        self.usage += usage


def derived_seed(master_seed: int, namespace: str, index: int) -> int:
    payload = f"{master_seed}:{namespace}:{index}".encode("ascii")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def search_seed(master_seed: int, batch_number: int) -> int:
    return derived_seed(master_seed, "search", batch_number)


def research_lock_path(root: Path = ROOT) -> Path:
    return Path(root) / ".mini-igp8-research.lock"


def screening_decision(proposal: dict) -> tuple[bool, str]:
    if int(proposal.get("verified", 0)) == 0:
        return False, "rejected_screening_no_verified_candidates"
    return True, "screening_passed"


def paired_race_metrics(incumbent_fresh: dict, proposal_fresh: dict) -> dict:
    incumbent_counts = incumbent_fresh.get("_fresh_seed_pair_counts", {})
    proposal_counts = proposal_fresh.get("_fresh_seed_pair_counts", {})
    if set(incumbent_counts) != set(proposal_counts):
        raise ValueError("fresh_comparison_seed_mismatch")
    incumbent_wins = proposal_wins = ties = 0
    for seed in incumbent_counts:
        old = int(incumbent_counts[seed])
        new = int(proposal_counts[seed])
        if new > old:
            proposal_wins += 1
        elif old > new:
            incumbent_wins += 1
        else:
            ties += 1
    return {
        "seeds": len(incumbent_counts),
        "incumbent_seed_wins": incumbent_wins,
        "proposal_seed_wins": proposal_wins,
        "seed_ties": ties,
        "incumbent_seed_hits": int(incumbent_fresh.get("fresh_seed_hits", 0)),
        "proposal_seed_hits": int(proposal_fresh.get("fresh_seed_hits", 0)),
        "incumbent_pair_hits": int(incumbent_fresh.get("fresh_pair_hits", 0)),
        "proposal_pair_hits": int(proposal_fresh.get("fresh_pair_hits", 0)),
        "incumbent_distinct_missing_pairs": int(incumbent_fresh.get("fresh_new_pairs", 0)),
        "proposal_distinct_missing_pairs": int(proposal_fresh.get("fresh_new_pairs", 0)),
    }


def acceptance_decision(
    incumbent_benchmark: dict,
    proposal_benchmark: dict,
    incumbent_fresh: dict,
    proposal_fresh: dict,
    incumbent_discriminants: dict | None = None,
    proposal_discriminants: dict | None = None,
) -> tuple[bool, str]:
    """Lexicographic objective: missing pairs first, discriminants second, benchmark third."""

    old_fresh = int(incumbent_fresh.get("fresh_new_pairs", 0))
    new_fresh = int(proposal_fresh.get("fresh_new_pairs", 0))
    if new_fresh != old_fresh:
        return (new_fresh > old_fresh, "accepted_discovery_gain" if new_fresh > old_fresh else "rejected_fresh_discovery_regression")

    old_seed_hits = int(incumbent_fresh.get("fresh_seed_hits", 0))
    new_seed_hits = int(proposal_fresh.get("fresh_seed_hits", 0))
    if new_seed_hits != old_seed_hits:
        return (new_seed_hits > old_seed_hits, "accepted_seed_consistency_gain" if new_seed_hits > old_seed_hits else "rejected_seed_consistency_regression")

    old_pair_hits = int(incumbent_fresh.get("fresh_pair_hits", 0))
    new_pair_hits = int(proposal_fresh.get("fresh_pair_hits", 0))
    if new_pair_hits != old_pair_hits:
        return (new_pair_hits > old_pair_hits, "accepted_missing_pair_hit_gain" if new_pair_hits > old_pair_hits else "rejected_missing_pair_hit_regression")

    paired = paired_race_metrics(incumbent_fresh, proposal_fresh)
    if paired["proposal_seed_wins"] != paired["incumbent_seed_wins"]:
        accepted = paired["proposal_seed_wins"] > paired["incumbent_seed_wins"]
        return accepted, "accepted_paired_seed_win_gain" if accepted else "rejected_paired_seed_win_regression"

    old_disc = incumbent_discriminants or {}
    new_disc = proposal_discriminants or {}
    old_count = int(old_disc.get("improvements", 0))
    new_count = int(new_disc.get("improvements", 0))
    if new_count != old_count:
        return (new_count > old_count, "accepted_discriminant_improvement_gain" if new_count > old_count else "rejected_discriminant_improvement_regression")
    if new_count > 0:
        old_ratio = float(old_disc.get("best_ratio", 1.0))
        new_ratio = float(new_disc.get("best_ratio", 1.0))
        if new_ratio != old_ratio:
            return (new_ratio < old_ratio, "accepted_discriminant_magnitude_gain" if new_ratio < old_ratio else "rejected_discriminant_magnitude_regression")

    old_score = float(incumbent_benchmark["score"])
    new_score = float(proposal_benchmark["score"])
    if new_score > old_score:
        return True, "accepted_benchmark_gain"
    return False, "rejected_no_measured_gain"


def race_checkpoint_decision(
    incumbent_benchmark: dict,
    proposal_benchmark: dict,
    incumbent_fresh: dict,
    proposal_fresh: dict,
    *,
    round_index: int,
    total_rounds: int,
) -> tuple[str, str]:
    if round_index >= total_rounds - 1:
        accepted, reason = acceptance_decision(
            incumbent_benchmark, proposal_benchmark, incumbent_fresh, proposal_fresh
        )
        return ("accept" if accepted else "reject"), reason

    paired = paired_race_metrics(incumbent_fresh, proposal_fresh)
    distinct_margin = paired["proposal_distinct_missing_pairs"] - paired["incumbent_distinct_missing_pairs"]
    seed_win_margin = paired["proposal_seed_wins"] - paired["incumbent_seed_wins"]
    hit_margin = paired["proposal_pair_hits"] - paired["incumbent_pair_hits"]

    if round_index == 0:
        if (
            paired["proposal_seed_hits"] == 0 and paired["incumbent_seed_hits"] >= 3
        ) or (distinct_margin <= -2 and seed_win_margin <= -3 and hit_margin <= -3):
            return "reject", "rejected_clear_round1_regression"
        return "continue", "race_requires_more_evidence"

    if distinct_margin >= 2 and seed_win_margin >= 3 and hit_margin >= 3:
        return "accept", "accepted_clear_round2_gain"
    if distinct_margin <= -2 and seed_win_margin <= -3 and hit_margin <= -3:
        return "reject", "rejected_clear_round2_regression"
    if paired["proposal_seed_hits"] == 0 and paired["incumbent_seed_hits"] >= 4:
        return "reject", "rejected_no_missing_pair_seed_hits"
    return "continue", "race_requires_more_evidence"


def _changed_paths(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=root, capture_output=True, text=True, check=False,
    )
    if result.returncode:
        raise ResearchStop("git_status_failed", result.stderr.strip()[:300])
    paths: list[str] = []
    for line in result.stdout.splitlines():
        if len(line) >= 4:
            paths.extend(piece.strip() for piece in line[3:].split(" -> "))
    return sorted(set(paths))


def _safe_working_tree(root: Path) -> None:
    allowed = {f"results/{name}" for name in RESULT_FILENAMES}
    unexpected = [path for path in _changed_paths(root) if path not in allowed]
    if unexpected:
        raise ResearchStop("working_tree_has_manual_changes", ",".join(unexpected))


def _full_tests(root: Path) -> None:
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
            cwd=root, capture_output=True, text=True, check=False, timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        raise ResearchStop("repository_self_test_timeout") from exc
    if completed.returncode:
        detail = "\n".join((completed.stdout + completed.stderr).splitlines()[-14:])
        raise ResearchStop("repository_self_test_failed", detail)


def _metric_summary(summary: dict) -> dict:
    keys = (
        "score", "pairs", "groups", "verified", "candidate_slots", "verified_fraction",
        "status_counts", "sage_calls", "fresh_new_pairs", "fresh_seed_count",
        "fresh_seed_hits", "fresh_pair_hits",
    )
    return {key: summary[key] for key in keys if key in summary}


def _experiment_row(**values: object) -> dict:
    row = {field: "" for field in EXPERIMENT_FIELDS}
    row.update(values)
    return row


def _initialize_workspace(path: Path, solver_source: str, task_text: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "solver.py").write_text(solver_source, encoding="utf-8")
    (path / "TASK.md").write_text(task_text, encoding="utf-8")
    (path / ".gitignore").write_text("__pycache__/\n*.pyc\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Mini-IGP8 Candidate"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "candidate@invalid.local"], cwd=path, check=True)
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "candidate baseline"], cwd=path, check=True)


def _initialize_readonly_workspace(path: Path, role: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "README.md").write_text(f"Mini-IGP8 {role} workspace.\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def _research_prompt(store: Store, state: dict, config: Config) -> str:
    catalogue = store.catalogue()
    discovered = {(entry["galois_group"], int(entry["real_roots"])) for entry in catalogue.values()}
    targets = load_target_pairs(store.root / "data" / "targets.json")
    groups = sorted({group for group, _ in targets}, key=lambda group: int(group[2:]))
    coverage = [
        {
            "group": group,
            "found_r": sorted(root for candidate_group, root in discovered if candidate_group == group),
            "missing_r": sorted(root for candidate_group, root in targets - discovered if candidate_group == group),
        }
        for group in groups
    ]
    recent = []
    for row in store.experiments()[-12:]:
        recent.append({
            "generation": row["generation"],
            "candidate_id": row["candidate_id"],
            "accepted": row["accepted"],
            "stage": row["stage"],
            "reason_code": row["reason_code"],
            "screen_score": row["screen_score"],
            "benchmark_score": row["benchmark_score"],
            "fresh_missing_pairs": row["fresh_missing_pairs"],
            "fresh_seed_hits": row["fresh_seed_hits"],
            "discriminant_improvements": row["discriminant_improvements"],
            "hypothesis": row["hypothesis"][:350],
        })
    discrim = [
        {
            "pair": f"{entry['galois_group']}|{entry['real_roots']}",
            "field_discriminant": int(entry["field_discriminant"]),
        }
        for entry in catalogue.values() if entry.get("field_discriminant") is not None
    ]
    discrim.sort(key=lambda item: item["field_discriminant"], reverse=True)
    context = {
        "solver_source": (store.root / "mini_igp8" / "solver.py").read_text(encoding="utf-8"),
        "coverage_by_group": coverage,
        "catalogue_pairs": len(catalogue),
        "target_pairs": len(targets),
        "large_discriminant_secondary_opportunities": discrim[:12],
        "recent_solver_experiments": recent,
        "previous_generation_critic": state.get("generation_feedback"),
        "current_frozen_metrics": state.get("incumbent_benchmark"),
        "evaluation_shape": {
            "five_parallel_terra_candidates": True,
            "screening_slots_per_candidate": config.screening_slots,
            "frozen_benchmark_slots_per_survivor": config.benchmark_slots,
            "preliminary_fresh_seeds_max": sum(config.fresh_round_seed_counts),
            "final_fresh_seeds_max": sum(config.final_round_seed_counts),
            "exact_hidden_seed_values": "withheld",
        },
    }
    rules = """
You are the lead mathematical researcher for one Mini-IGP8 generation. Produce EXACTLY five
meaningfully different hypotheses A-E for five independent Terra implementers. Do not give five
small parameter tweaks of the same idea.

Primary objective: discover currently missing degree-8 target pairs (8Tn,r), especially entire
missing transitive groups and missing signatures. Secondary objective: when it comes naturally,
produce smaller absolute NUMBER-FIELD discriminants for already-solved pairs. A new missing pair
always outranks any number of easy discriminant improvements while missing pairs remain.

Diversify the five missions: (A) attack entirely missing groups, (B) attack missing signatures in
partially covered groups, (C) introduce a genuinely different algebraic/structured construction,
(D) exploit and improve useful incumbent mechanisms without merely copying them, and (E) design a
complementary portfolio/exploration strategy that may also improve difficult discriminant records.
You may reinterpret those missions mathematically, but they must remain genuinely orthogonal.

The solver contract is only: generate exactly budget UNIQUE deterministic monic degree-8 integer
vectors [a0,...,a8], with a8=1 and a0!=0. There is no coefficient magnitude bound and no symmetry
requirement. Never hard-code catalogue polynomials, target answers, or hidden seeds. Use the prior
generation critic and measured history. Return the required JSON only.
""".strip()
    return rules + "\n\nEXPERIMENT CONTEXT\n" + json.dumps(context, sort_keys=True)


def _candidate_rank(candidate: dict, incumbent_fresh: dict) -> tuple:
    fresh = candidate.get("fresh") or candidate.get("screen_fresh") or {}
    benchmark = candidate.get("benchmark") or candidate.get("screen") or {}
    paired_margin = 0
    if fresh.get("_fresh_seed_pair_counts") and incumbent_fresh.get("_fresh_seed_pair_counts"):
        paired = paired_race_metrics(incumbent_fresh, fresh)
        paired_margin = paired["proposal_seed_wins"] - paired["incumbent_seed_wins"]
    disc = candidate.get("discriminants") or {}
    best_ratio = float(disc.get("best_ratio", 1.0))
    return (
        int(fresh.get("fresh_new_pairs", 0)),
        int(fresh.get("fresh_seed_hits", 0)),
        int(fresh.get("fresh_pair_hits", 0)),
        paired_margin,
        int(disc.get("improvements", 0)),
        -best_ratio,
        float(benchmark.get("score", 0.0)),
    )


class ResearchController:
    def __init__(
        self,
        *,
        root: Path = ROOT,
        llm: CodexClient | None = None,
        verifier=verify,
        field_discriminant_fn=field_discriminant,
        run_tests=_full_tests,
        progress: Callable[[str], None] | None = None,
    ):
        self.root = Path(root).resolve()
        self.store = Store(self.root)
        self.config = load_config(self.root / "config.toml")
        self.llm = llm or CodexClient()
        self.verifier = verifier
        self.field_discriminant_fn = field_discriminant_fn
        self.run_tests = run_tests
        self.progress = progress or (lambda _message: None)
        self.solver_file = self.root / "mini_igp8" / "solver.py"
        self.candidate_root = self.root / "candidates" / "current"

    def _say(self, message: str) -> None:
        self.progress(message)

    def _stage_progress(self, label: str) -> Callable[[int, int], None]:
        return lambda done, total: self._say(f"{label}: {done}/{total}")

    @staticmethod
    def _usage_delta(after: TokenUsage, before: TokenUsage) -> TokenUsage:
        return TokenUsage(
            after.input_tokens - before.input_tokens,
            after.cached_input_tokens - before.cached_input_tokens,
            after.output_tokens - before.output_tokens,
            after.reasoning_tokens - before.reasoning_tokens,
        )

    def _cleanup_candidate_workspace(self) -> None:
        if self.candidate_root.exists():
            shutil.rmtree(self.candidate_root)

    def _validate_solver(self, path: Path) -> None:
        validate_solver_contract(
            path,
            timeout_seconds=self.config.solver_seconds,
            known_polynomials=self.store.known_polynomials(),
            held_out_seeds=set(self.config.benchmark_seeds) | set(self.config.screening_seeds),
            stress_budget=self.config.batch_size * self.config.search_oversample,
        )

    def _ensure_run_identity(self, state: dict) -> None:
        if state["run_id"] is not None:
            return
        if self.store.catalogue() or self.store.experiments() or state["search_candidates_total"]:
            raise ResearchStop("unidentified_nonempty_run_state")
        head = git("rev-parse", "HEAD", root=self.root)
        if not head:
            raise ResearchStop("git_repository_missing")
        state["run_id"] = uuid.uuid4().hex[:12]
        state["accepted_solver_commit"] = head
        self.store.save_state(state)

    def _check_state_consistency(self, state: dict) -> None:
        rows = self.store.experiments()
        catalogue = self.store.catalogue()
        seen = self.store.seen_hashes()
        if state["run_id"] is None:
            dirty: list[str] = []
            if state != initial_state():
                dirty.append("state")
            if rows:
                dirty.append("experiments")
            if catalogue:
                dirty.append("catalogue")
            if seen:
                dirty.append("seen_hashes")
            if self.store.history_file.read_text(encoding="utf-8").strip():
                dirty.append("history")
            baseline = self.root / "mini_igp8" / "baseline_solver.py"
            if self.solver_file.read_bytes().replace(b"\r\n", b"\n") != baseline.read_bytes().replace(b"\r\n", b"\n"):
                dirty.append("solver")
            if dirty:
                raise ResearchStop("clean_slate_invariant_failed", ",".join(dirty))

        expected_generation = max((int(row["generation"]) for row in rows), default=-1) + 1
        if rows and rows[0]["stage"] == "baseline":
            expected_generation = max(1, expected_generation)
        elif not rows:
            expected_generation = 0
        if state["next_generation"] != expected_generation:
            raise ResearchStop(
                "state_generation_cursor_mismatch",
                f"state={state['next_generation']}:csv={expected_generation}",
            )
        if not (0 <= state["last_new_pair_at"] <= state["search_candidates_total"]):
            raise ResearchStop("state_last_new_pair_out_of_range")
        if not (0 <= state["last_solver_change_at"] <= state["search_candidates_total"]):
            raise ResearchStop("state_last_solver_change_out_of_range")
        if len(seen) > state["search_candidates_total"]:
            raise ResearchStop("seen_hash_count_exceeds_search_count")
        cached_hash = state.get("incumbent_solver_hash")
        cached_benchmark = state.get("incumbent_benchmark")
        if bool(cached_hash) != bool(cached_benchmark):
            raise ResearchStop("partial_incumbent_cache")
        if cached_hash and cached_hash != solver_sha256(self.solver_file):
            raise ResearchStop("solver_state_hash_mismatch")

    def _ensure_baseline(self, state: dict, budget: Budget, session_id: str) -> None:
        if state.get("incumbent_benchmark"):
            return
        self._say(f"baseline: measuring {self.config.benchmark_slots} frozen benchmark slots")
        benchmark, _records, _hashes = evaluate_fixed(
            self.solver_file,
            seeds=self.config.benchmark_seeds,
            candidates_per_seed=self.config.benchmark_size,
            solver_seconds=self.config.solver_seconds,
            verification_seconds=self.config.verification_seconds,
            verifier=self.verifier,
            deadline=budget.deadline,
            progress=self._stage_progress("baseline benchmark"),
            progress_every=self.config.progress_every,
        )
        budget.spend_sage(benchmark["sage_calls"])
        state["incumbent_benchmark"] = _metric_summary(benchmark)
        state["incumbent_solver_hash"] = solver_sha256(self.solver_file)
        state["next_generation"] = 1
        event = self.store.append_history(
            "baseline_measured", {"benchmark": _metric_summary(benchmark)}, session_id=session_id
        )
        self.store.append_experiment(_experiment_row(
            generation=0,
            candidate_id="incumbent",
            timestamp=now(),
            accepted="yes",
            stage="baseline",
            reason_code="baseline_measured",
            label="naive baseline",
            hypothesis="uniform small-coefficient random monic octics",
            benchmark_score=f"{benchmark['score']:.12f}",
            benchmark_pairs=benchmark["pairs"],
            catalogue_pairs_before=len(self.store.catalogue()),
            catalogue_pairs_after=len(self.store.catalogue()),
            catalogue_groups_after=len({e["galois_group"] for e in self.store.catalogue().values()}),
            verified_fraction=f"{benchmark['verified_fraction']:.12f}",
            sage_calls=benchmark["sage_calls"],
            ai_calls=0,
            solver_commit=state["accepted_solver_commit"] or "",
            solver_hash=state["incumbent_solver_hash"],
            session_id=session_id,
        ))
        self.store.save_state(state)
        self.store.append_history("baseline_public_catalogue_unchanged", {"source_event": event}, session_id=session_id)

    def _ask_researcher(self, state: dict, budget: Budget, generation_dir: Path) -> tuple[dict, TokenUsage]:
        workspace = generation_dir / "researcher"
        _initialize_readonly_workspace(workspace, "lead researcher")
        ensure_codex()
        budget.reserve_ai(1)
        response = self.llm.call(
            prompt=_research_prompt(self.store, state, self.config),
            cwd=workspace,
            model=self.config.researcher_model,
            reasoning=self.config.researcher_reasoning,
            sandbox="read-only",
            timeout=min(budget.seconds_left, self.config.ai_seconds),
            schema=RESEARCH_SCHEMA,
        )
        budget.add_usage(response.usage)
        if response.data is None:
            raise ResearchStop("researcher_missing_structured_output")
        hypotheses = response.data.get("hypotheses", [])
        ids = [item.get("candidate_id") for item in hypotheses]
        if sorted(ids) != ["A", "B", "C", "D", "E"]:
            raise ResearchStop("researcher_candidate_ids_invalid", str(ids))
        return response.data, response.usage

    def _implement_worker(self, hypothesis: dict, workspace: Path, timeout: float) -> tuple[str, TokenUsage]:
        source = self.solver_file.read_text(encoding="utf-8")
        task = (
            "Edit solver.py only. Implement the supplied hypothesis faithfully. Do not create files, commit, "
            "read the parent repository, hard-code target answers, catalogue polynomials, or hidden seeds.\n\n"
            + json.dumps(hypothesis, indent=2, sort_keys=True)
        )
        _initialize_workspace(workspace, source, task)
        prompt = json.dumps({
            "role": "parallel Terra implementer",
            "task": "Edit solver.py only and implement this one hypothesis as a production candidate.",
            "hypothesis": hypothesis,
            "contract": {
                "format": "exactly budget unique monic degree-8 integer vectors [a0,...,a8]",
                "required": "a8=1, a0!=0, deterministic for seed and budget",
                "coefficient_bound": "none",
            },
            "priorities": [
                "Missing target-pair discovery is primary.",
                "Smaller field discriminants for solved pairs are secondary.",
                "Keep coefficient generation fast: 2,000 candidates must complete comfortably within the solver timeout.",
                "Use bounded deterministic generation; avoid unbounded rejection loops or expensive algebraic verification inside solver.py.",
                "Edit solver.py only; do not create files or commit.",
            ],
        }, sort_keys=True)
        response = self.llm.call(
            prompt=prompt,
            cwd=workspace,
            model=self.config.implementer_model,
            reasoning=self.config.implementer_reasoning,
            sandbox="workspace-write",
            timeout=timeout,
        )
        changed = _changed_paths(workspace)
        if changed != ["solver.py"]:
            raise SolverError(f"implementer_changed_forbidden_paths:{changed}")
        proposed = (workspace / "solver.py").read_text(encoding="utf-8")
        if proposed == source:
            raise SolverError("implementer_made_no_change")
        return proposed, response.usage

    def _parallel_implement(self, hypotheses: list[dict], budget: Budget, generation_dir: Path) -> list[dict]:
        ensure_codex()
        budget.reserve_ai(len(hypotheses))
        timeout = min(budget.seconds_left, self.config.ai_seconds)
        results: list[dict] = []
        workers = min(self.config.parallel_implementers, len(hypotheses))
        self._say(f"generation: launching {len(hypotheses)} Terra implementers concurrently ({workers} workers)")
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="mini-igp8-terra") as pool:
            future_map = {
                pool.submit(
                    self._implement_worker,
                    hypothesis,
                    generation_dir / f"candidate-{hypothesis['candidate_id']}",
                    timeout,
                ): hypothesis
                for hypothesis in hypotheses
            }
            for future in as_completed(future_map):
                hypothesis = future_map[future]
                candidate = {
                    "id": hypothesis["candidate_id"],
                    "hypothesis": hypothesis,
                    "workspace": generation_dir / f"candidate-{hypothesis['candidate_id']}",
                    "ai_calls": 1,
                    "usage": TokenUsage(),
                    "status": "implementation_failed",
                    "reason": "implementation_failed",
                    "eval_hashes": set(),
                    "sage_calls": 0,
                }
                try:
                    source, usage = future.result()
                    budget.add_usage(usage)
                    candidate["usage"] = usage
                    candidate["source"] = source
                    candidate["path"] = candidate["workspace"] / "solver.py"
                    candidate["hash"] = solver_sha256(candidate["path"])
                    self._validate_solver(candidate["path"])
                    candidate["status"] = "implemented"
                    candidate["reason"] = "implemented"
                    self._say(f"candidate {candidate['id']}: implementation and contract validation passed")
                except (CodexFailure, SolverError, OSError, ValueError) as exc:
                    if isinstance(exc, CodexFailure):
                        candidate["reason"] = exc.code
                    else:
                        candidate["reason"] = str(exc).split(":", 1)[0]
                    self._say(f"candidate {candidate['id']}: rejected during implementation ({candidate['reason']})")
                results.append(candidate)
        return sorted(results, key=lambda item: item["id"])

    def _screen_candidates(self, candidates: list[dict], budget: Budget, catalogue_pairs: set[tuple[str, int]]) -> list[dict]:
        passed: list[dict] = []
        for candidate in candidates:
            if candidate["status"] != "implemented":
                continue
            self._say(f"candidate {candidate['id']}: screening {self.config.screening_slots} slots")
            try:
                summary, records, hashes = evaluate_fixed(
                    candidate["path"],
                    seeds=self.config.screening_seeds,
                    candidates_per_seed=self.config.screening_size,
                    solver_seconds=self.config.solver_seconds,
                    verification_seconds=self.config.verification_seconds,
                    verifier=self.verifier,
                    deadline=budget.deadline,
                    progress=self._stage_progress(f"candidate {candidate['id']} screen"),
                    progress_every=self.config.progress_every,
                )
            except (SolverError, EvaluationDeadlineExceeded) as exc:
                candidate["status"] = "screen_rejected"
                candidate["reason"] = str(exc).split(":", 1)[0]
                continue
            budget.spend_sage(summary["sage_calls"])
            candidate["sage_calls"] = candidate.get("sage_calls", 0) + summary["sage_calls"]
            candidate["screen"] = summary
            candidate["screen_records"] = records
            candidate["screen_fresh"] = summarize_fresh_records(records, catalogue_pairs=catalogue_pairs)
            candidate["eval_hashes"].update(hashes)
            ok, reason = screening_decision(summary)
            if ok:
                candidate["status"] = "screen_passed"
                candidate["reason"] = reason
                passed.append(candidate)
            else:
                candidate["status"] = "screen_rejected"
                candidate["reason"] = reason

        passed.sort(
            key=lambda c: (
                int(c["screen_fresh"].get("fresh_new_pairs", 0)),
                int(c["screen_fresh"].get("fresh_seed_hits", 0)),
                float(c["screen"].get("score", 0.0)),
            ),
            reverse=True,
        )
        survivors = passed[:self.config.max_screen_survivors]
        survivor_ids = {c["id"] for c in survivors}
        for candidate in passed[self.config.max_screen_survivors:]:
            candidate["status"] = "screen_pruned"
            candidate["reason"] = "screen_pruned_to_top_survivors"
        self._say(f"generation: screen survivors={','.join(sorted(survivor_ids)) or 'none'}")
        return survivors

    def _benchmark_candidates(self, candidates: list[dict], budget: Budget) -> list[dict]:
        passed: list[dict] = []
        for candidate in candidates:
            self._say(f"candidate {candidate['id']}: frozen benchmark {self.config.benchmark_slots} slots")
            try:
                summary, _records, hashes = evaluate_fixed(
                    candidate["path"],
                    seeds=self.config.benchmark_seeds,
                    candidates_per_seed=self.config.benchmark_size,
                    solver_seconds=self.config.solver_seconds,
                    verification_seconds=self.config.verification_seconds,
                    verifier=self.verifier,
                    deadline=budget.deadline,
                    progress=self._stage_progress(f"candidate {candidate['id']} benchmark"),
                    progress_every=self.config.progress_every,
                )
            except SolverError as exc:
                candidate["status"] = "benchmark_rejected"
                candidate["reason"] = str(exc).split(":", 1)[0]
                self._say(
                    f"candidate {candidate['id']}: rejected during benchmark ({candidate['reason']})"
                )
                continue
            budget.spend_sage(summary["sage_calls"])
            candidate["sage_calls"] = candidate.get("sage_calls", 0) + summary["sage_calls"]
            candidate["benchmark"] = summary
            candidate["eval_hashes"].update(hashes)
            passed.append(candidate)
        return passed

    def _preliminary_race(
        self,
        candidates: list[dict],
        *,
        generation: int,
        budget: Budget,
        public_seen: set[str],
        catalogue_pairs: set[tuple[str, int]],
    ) -> tuple[list[dict], dict]:
        incumbent_records: list[dict] = []
        incumbent_seen = set(public_seen)
        for candidate in candidates:
            candidate["prelim_records"] = []
            candidate["prelim_seen"] = set(public_seen) | set(candidate["eval_hashes"])
        active = list(candidates)
        passed: list[dict] = []
        seed_cursor = 0
        incumbent_fresh: dict = {"_fresh_seed_pair_counts": {}}

        for round_index, seed_count in enumerate(self.config.fresh_round_seed_counts):
            if not active:
                break
            first = seed_cursor + 1
            seed_cursor += seed_count
            seeds = tuple(
                derived_seed(self.config.comparison_master_seed, f"generation-{generation}-prelim", index)
                for index in range(first, seed_cursor + 1)
            )
            self._say(
                f"generation {generation}: preliminary race round {round_index + 1}, "
                f"{seed_count} new shared seeds ({seed_cursor} total)"
            )
            inc_summary, inc_records, inc_hashes = evaluate_fresh(
                self.solver_file,
                seeds=seeds,
                candidates_per_seed=self.config.fresh_size,
                oversample_factor=self.config.fresh_oversample,
                catalogue_pairs=catalogue_pairs,
                already_seen=incumbent_seen,
                solver_seconds=self.config.solver_seconds,
                verification_seconds=self.config.verification_seconds,
                verifier=self.verifier,
                deadline=budget.deadline,
                progress=self._stage_progress(f"generation {generation} incumbent prelim r{round_index + 1}"),
                progress_every=self.config.progress_every,
            )
            budget.spend_sage(inc_summary["sage_calls"])
            incumbent_seen.update(inc_hashes)
            incumbent_records.extend(inc_records)
            incumbent_fresh = summarize_fresh_records(incumbent_records, catalogue_pairs=catalogue_pairs)

            still_active: list[dict] = []
            for candidate in active:
                try:
                    summary, records, hashes = evaluate_fresh(
                        candidate["path"],
                        seeds=seeds,
                        candidates_per_seed=self.config.fresh_size,
                        oversample_factor=self.config.fresh_oversample,
                        catalogue_pairs=catalogue_pairs,
                        already_seen=candidate["prelim_seen"],
                        solver_seconds=self.config.solver_seconds,
                        verification_seconds=self.config.verification_seconds,
                        verifier=self.verifier,
                        deadline=budget.deadline,
                        progress=self._stage_progress(
                            f"candidate {candidate['id']} prelim r{round_index + 1}"
                        ),
                        progress_every=self.config.progress_every,
                    )
                except SolverError as exc:
                    candidate["status"] = "preliminary_rejected"
                    candidate["reason"] = str(exc).split(":", 1)[0]
                    candidate["prelim_reason"] = candidate["reason"]
                    candidate["prelim_seeds"] = seed_cursor
                    self._say(
                        f"candidate {candidate['id']}: preliminary rejection "
                        f"({candidate['reason']})"
                    )
                    continue
                budget.spend_sage(summary["sage_calls"])
                candidate["sage_calls"] = candidate.get("sage_calls", 0) + summary["sage_calls"]
                candidate["prelim_seen"].update(hashes)
                candidate["eval_hashes"].update(hashes)
                candidate["prelim_records"].extend(records)
                candidate["fresh"] = summarize_fresh_records(
                    candidate["prelim_records"], catalogue_pairs=catalogue_pairs
                )
                action, reason = race_checkpoint_decision(
                    self.store.state()["incumbent_benchmark"],
                    candidate["benchmark"],
                    incumbent_fresh,
                    candidate["fresh"],
                    round_index=round_index,
                    total_rounds=len(self.config.fresh_round_seed_counts),
                )
                candidate["prelim_reason"] = reason
                candidate["prelim_seeds"] = seed_cursor
                if action == "accept":
                    candidate["status"] = "preliminary_passed"
                    passed.append(candidate)
                    self._say(f"candidate {candidate['id']}: passed preliminary race ({reason})")
                elif action == "reject":
                    candidate["status"] = "preliminary_rejected"
                    candidate["reason"] = reason
                    self._say(f"candidate {candidate['id']}: preliminary rejection ({reason})")
                else:
                    still_active.append(candidate)
            active = still_active

        passed.sort(key=lambda candidate: _candidate_rank(candidate, incumbent_fresh), reverse=True)
        return passed[:self.config.max_synthesis_finalists], incumbent_fresh

    def _synthesize(
        self,
        finalists: list[dict],
        *,
        generation: int,
        budget: Budget,
        generation_dir: Path,
        catalogue_pairs: set[tuple[str, int]],
    ) -> dict | None:
        if len(finalists) < 2:
            return None
        # Preserve one call for the mandatory generation critic.
        if budget.ai_left < 3:
            self._say("synthesis skipped: preserving remaining AI budget for generation critic")
            return None

        synthesis_workspace = generation_dir / "synthesis-research"
        _initialize_readonly_workspace(synthesis_workspace, "synthesis researcher")
        payload = {
            "role": "Sol synthesis researcher",
            "task": (
                "Design one coherent solver that combines complementary mechanisms from the finalists. "
                "Do not mechanically concatenate programs. Explain a principled portfolio/family composition."
            ),
            "primary_objective": "missing target pairs",
            "secondary_objective": "smaller field discriminants for already-solved pairs",
            "incumbent_source": self.solver_file.read_text(encoding="utf-8"),
            "finalists": [
                {
                    "candidate_id": c["id"],
                    "hypothesis": c["hypothesis"],
                    "source": c["source"],
                    "benchmark": _metric_summary(c["benchmark"]),
                    "fresh": _metric_summary(c["fresh"]),
                }
                for c in finalists
            ],
            "hidden_seed_values": "withheld",
        }
        budget.reserve_ai(1)
        response = self.llm.call(
            prompt=json.dumps(payload, sort_keys=True),
            cwd=synthesis_workspace,
            model=self.config.synthesizer_model,
            reasoning=self.config.synthesizer_reasoning,
            sandbox="read-only",
            timeout=min(budget.seconds_left, self.config.ai_seconds),
            schema=SYNTHESIS_SCHEMA,
        )
        budget.add_usage(response.usage)
        if response.data is None:
            return None

        best = finalists[0]
        workspace = generation_dir / "candidate-S"
        references = {
            "synthesis_plan": response.data,
            "finalists": [
                {"candidate_id": c["id"], "hypothesis": c["hypothesis"], "source": c["source"]}
                for c in finalists
            ],
        }
        _initialize_workspace(
            workspace,
            best["source"],
            "Edit solver.py only. Use this synthesis plan and references:\n\n"
            + json.dumps(references, indent=2, sort_keys=True),
        )
        prompt = json.dumps({
            "role": "Terra synthesis implementer",
            "task": "Edit solver.py only to implement the Sol synthesis plan coherently.",
            "synthesis_plan": response.data,
            "rules": [
                "Use TASK.md only as reference; edit solver.py only.",
                "Do not create files or commit.",
                "Do not hard-code known answers or hidden seeds.",
                "Primary objective is missing-pair discovery; discriminant reduction is secondary.",
                "Keep coefficient generation fast: 2,000 candidates must complete comfortably within the solver timeout.",
                "Use bounded deterministic generation; avoid unbounded rejection loops or expensive algebraic verification inside solver.py.",
            ],
        }, sort_keys=True)
        budget.reserve_ai(1)
        implement = self.llm.call(
            prompt=prompt,
            cwd=workspace,
            model=self.config.implementer_model,
            reasoning=self.config.implementer_reasoning,
            sandbox="workspace-write",
            timeout=min(budget.seconds_left, self.config.ai_seconds),
        )
        budget.add_usage(implement.usage)
        changed = _changed_paths(workspace)
        if changed != ["solver.py"]:
            self._say(f"synthesized candidate rejected: changed paths {changed}")
            return None
        source = (workspace / "solver.py").read_text(encoding="utf-8")
        if source == best["source"]:
            self._say("synthesized candidate rejected: no code change")
            return None
        candidate = {
            "id": "S",
            "hypothesis": {
                "candidate_id": "S",
                "label": "synthesized finalist",
                "mission": "combine complementary passing mechanisms",
                "hypothesis": response.data["thesis"],
            },
            "workspace": workspace,
            "path": workspace / "solver.py",
            "source": source,
            "hash": solver_sha256(workspace / "solver.py"),
            "usage": response.usage + implement.usage,
            "ai_calls": 2,
            "status": "implemented",
            "reason": "synthesized",
            "eval_hashes": set(),
            "sage_calls": 0,
        }
        try:
            self._validate_solver(candidate["path"])
            screen, records, hashes = evaluate_fixed(
                candidate["path"],
                seeds=self.config.screening_seeds,
                candidates_per_seed=self.config.screening_size,
                solver_seconds=self.config.solver_seconds,
                verification_seconds=self.config.verification_seconds,
                verifier=self.verifier,
                deadline=budget.deadline,
                progress=self._stage_progress("synthesized screen"),
                progress_every=self.config.progress_every,
            )
            budget.spend_sage(screen["sage_calls"])
            candidate["sage_calls"] += screen["sage_calls"]
            candidate["screen"] = screen
            candidate["screen_fresh"] = summarize_fresh_records(records, catalogue_pairs=catalogue_pairs)
            candidate["eval_hashes"].update(hashes)
            ok, reason = screening_decision(screen)
            if not ok:
                candidate["status"] = "screen_rejected"
                candidate["reason"] = reason
                return candidate
            benchmark, _records, hashes = evaluate_fixed(
                candidate["path"],
                seeds=self.config.benchmark_seeds,
                candidates_per_seed=self.config.benchmark_size,
                solver_seconds=self.config.solver_seconds,
                verification_seconds=self.config.verification_seconds,
                verifier=self.verifier,
                deadline=budget.deadline,
                progress=self._stage_progress("synthesized benchmark"),
                progress_every=self.config.progress_every,
            )
            budget.spend_sage(benchmark["sage_calls"])
            candidate["sage_calls"] += benchmark["sage_calls"]
            candidate["benchmark"] = benchmark
            candidate["eval_hashes"].update(hashes)
            candidate["status"] = "synthesis_passed"
            return candidate
        except (SolverError, EvaluationDeadlineExceeded, ValueError) as exc:
            candidate["status"] = "synthesis_rejected"
            candidate["reason"] = str(exc).split(":", 1)[0]
            return candidate

    def _discriminant_probe(self, records: list[dict], budget: Budget) -> dict:
        limit = self.config.discriminant_checks_per_finalist
        if limit <= 0:
            return {"checked": 0, "improvements": 0, "best_ratio": 1.0}
        catalogue = self.store.catalogue()
        by_pair: dict[str, dict] = {}
        for record in records:
            if record.get("status") != "verified":
                continue
            key = self.store.pair_key(record["galois_group"], int(record["real_roots"]))
            entry = catalogue.get(key)
            if not entry or entry.get("field_discriminant") is None:
                continue
            if int(record["polynomial_discriminant"]) >= int(entry["polynomial_discriminant"]):
                continue
            previous = by_pair.get(key)
            if previous is None or int(record["polynomial_discriminant"]) < int(previous["polynomial_discriminant"]):
                by_pair[key] = record
        ranked = sorted(
            by_pair.items(),
            key=lambda item: int(item[1]["polynomial_discriminant"]) / max(1, int(catalogue[item[0]]["field_discriminant"])),
        )[:limit]
        improvements = 0
        best_ratio = 1.0
        checked = 0
        for key, record in ranked:
            if budget.seconds_left <= 0:
                break
            old = int(catalogue[key]["field_discriminant"])
            try:
                value = record.get("field_discriminant")
                if value is None:
                    value = self.field_discriminant_fn(
                        record["coefficients"],
                        timeout_seconds=min(self.config.verification_seconds, budget.seconds_left),
                    )
                value = abs(int(value))
                budget.spend_sage(1)
                checked += 1
            except Exception:
                continue
            if value < old:
                improvements += 1
                best_ratio = min(best_ratio, value / old)
        return {"checked": checked, "improvements": improvements, "best_ratio": best_ratio}

    def _final_race(
        self,
        challengers: list[dict],
        *,
        generation: int,
        budget: Budget,
        public_seen: set[str],
        catalogue_pairs: set[tuple[str, int]],
    ) -> tuple[dict | None, dict, list[dict]]:
        if not challengers:
            return None, {"fresh_new_pairs": 0, "_fresh_seed_pair_counts": {}}, []

        incumbent_records: list[dict] = []
        incumbent_seen = set(public_seen)
        for candidate in challengers:
            candidate["final_records"] = []
            candidate["final_seen"] = set(public_seen) | set(candidate.get("eval_hashes", set()))
        active = list(challengers)
        seed_cursor = 0
        incumbent_fresh: dict = {"_fresh_seed_pair_counts": {}}

        for round_index, seed_count in enumerate(self.config.final_round_seed_counts):
            if not active:
                break
            first = seed_cursor + 1
            seed_cursor += seed_count
            seeds = tuple(
                derived_seed(self.config.final_master_seed, f"generation-{generation}-final", index)
                for index in range(first, seed_cursor + 1)
            )
            self._say(
                f"generation {generation}: FINAL holdout round {round_index + 1}, "
                f"{seed_count} new shared seeds ({seed_cursor} total)"
            )
            inc_summary, records, hashes = evaluate_fresh(
                self.solver_file,
                seeds=seeds,
                candidates_per_seed=self.config.final_size,
                oversample_factor=self.config.final_oversample,
                catalogue_pairs=catalogue_pairs,
                already_seen=incumbent_seen,
                solver_seconds=self.config.solver_seconds,
                verification_seconds=self.config.verification_seconds,
                verifier=self.verifier,
                deadline=budget.deadline,
                progress=self._stage_progress(f"generation {generation} incumbent final r{round_index + 1}"),
                progress_every=self.config.progress_every,
            )
            budget.spend_sage(inc_summary["sage_calls"])
            incumbent_seen.update(hashes)
            incumbent_records.extend(records)
            incumbent_fresh = summarize_fresh_records(incumbent_records, catalogue_pairs=catalogue_pairs)

            round_survivors: list[dict] = []
            for candidate in active:
                try:
                    summary, records, hashes = evaluate_fresh(
                        candidate["path"],
                        seeds=seeds,
                        candidates_per_seed=self.config.final_size,
                        oversample_factor=self.config.final_oversample,
                        catalogue_pairs=catalogue_pairs,
                        already_seen=candidate["final_seen"],
                        solver_seconds=self.config.solver_seconds,
                        verification_seconds=self.config.verification_seconds,
                        verifier=self.verifier,
                        deadline=budget.deadline,
                        progress=self._stage_progress(f"candidate {candidate['id']} final r{round_index + 1}"),
                        progress_every=self.config.progress_every,
                    )
                except SolverError as exc:
                    candidate["status"] = "final_rejected"
                    candidate["reason"] = str(exc).split(":", 1)[0]
                    self._say(
                        f"candidate {candidate['id']}: final rejection ({candidate['reason']})"
                    )
                    continue
                budget.spend_sage(summary["sage_calls"])
                candidate["sage_calls"] = candidate.get("sage_calls", 0) + summary["sage_calls"]
                candidate["final_seen"].update(hashes)
                candidate["final_records"].extend(records)
                candidate["fresh"] = summarize_fresh_records(
                    candidate["final_records"], catalogue_pairs=catalogue_pairs
                )
                candidate["final_seeds"] = seed_cursor
                round_survivors.append(candidate)
            active = round_survivors

            if round_index == 0 and len(active) > self.config.final_max_challengers_after_round1:
                active.sort(key=lambda c: _candidate_rank(c, incumbent_fresh), reverse=True)
                pruned = active[self.config.final_max_challengers_after_round1:]
                for candidate in pruned:
                    candidate["status"] = "final_round1_pruned"
                    candidate["reason"] = "final_round1_pruned"
                active = active[:self.config.final_max_challengers_after_round1]
                self._say("final holdout: round-1 survivors=" + ",".join(c["id"] for c in active))

        incumbent_disc = self._discriminant_probe(incumbent_records, budget)
        for candidate in active:
            candidate["discriminants"] = self._discriminant_probe(candidate["final_records"], budget)
            candidate["sage_calls"] = candidate.get("sage_calls", 0) + candidate["discriminants"].get("checked", 0)

        active.sort(key=lambda c: _candidate_rank(c, incumbent_fresh), reverse=True)
        if not active:
            return None, incumbent_fresh, challengers
        best = active[0]
        accepted, reason = acceptance_decision(
            self.store.state()["incumbent_benchmark"],
            best["benchmark"],
            incumbent_fresh,
            best["fresh"],
            incumbent_disc,
            best.get("discriminants"),
        )
        best["final_reason"] = reason
        for candidate in active:
            if candidate is best and accepted:
                candidate["status"] = "final_winner"
                candidate["reason"] = reason
            else:
                candidate["status"] = "final_rejected"
                candidate["reason"] = reason if candidate is best else "final_lower_rank"
        if not accepted:
            return None, incumbent_fresh, challengers
        return best, incumbent_fresh, challengers

    def _record_candidate(self, candidate: dict, *, generation: int, session_id: str, accepted: bool, solver_commit: str = "") -> None:
        screen = candidate.get("screen") or {}
        screen_fresh = candidate.get("screen_fresh") or {}
        benchmark = candidate.get("benchmark") or {}
        fresh = candidate.get("fresh") or {}
        disc = candidate.get("discriminants") or {}
        usage = candidate.get("usage") or TokenUsage()
        catalogue = self.store.catalogue()
        reason = candidate.get("final_reason") or candidate.get("reason") or candidate.get("prelim_reason") or ""
        self.store.append_experiment(_experiment_row(
            generation=generation,
            candidate_id=candidate["id"],
            timestamp=now(),
            accepted="yes" if accepted else "no",
            stage="final" if accepted else candidate.get("status", "rejected"),
            reason_code=str(reason).split(":", 1)[0],
            label=candidate.get("hypothesis", {}).get("label", ""),
            hypothesis=candidate.get("hypothesis", {}).get("hypothesis", ""),
            screen_score=f"{float(screen.get('score', 0.0)):.12f}" if screen else "",
            screen_missing_pairs=screen_fresh.get("fresh_new_pairs", ""),
            benchmark_score=f"{float(benchmark.get('score', 0.0)):.12f}" if benchmark else "",
            benchmark_pairs=benchmark.get("pairs", ""),
            fresh_missing_pairs=fresh.get("fresh_new_pairs", ""),
            fresh_seed_hits=fresh.get("fresh_seed_hits", ""),
            fresh_pair_hits=fresh.get("fresh_pair_hits", ""),
            fresh_race_seeds=fresh.get("fresh_seed_count", ""),
            discriminant_improvements=disc.get("improvements", ""),
            best_discriminant_ratio=(f"{float(disc.get('best_ratio', 1.0)):.12f}" if disc else ""),
            catalogue_pairs_before=len(catalogue),
            catalogue_pairs_after=len(catalogue),
            catalogue_groups_after=len({entry["galois_group"] for entry in catalogue.values()}),
            verified_fraction=(f"{float(benchmark.get('verified_fraction', 0.0)):.12f}" if benchmark else ""),
            sage_calls=candidate.get("sage_calls", 0),
            ai_calls=candidate.get("ai_calls", 0),
            input_tokens=usage.input_tokens,
            cached_input_tokens=usage.cached_input_tokens,
            output_tokens=usage.output_tokens,
            reasoning_tokens=usage.reasoning_tokens,
            solver_commit=solver_commit,
            solver_hash=candidate.get("hash", ""),
            session_id=session_id,
        ))

    def _critic(self, state: dict, budget: Budget, session_id: str, generation: int, winner_id: str) -> None:
        if budget.ai_left < 1:
            self.store.append_history(
                "generation_critic_skipped", {"generation": generation, "reason": "ai_budget"}, session_id=session_id
            )
            return
        rows = [row for row in self.store.experiments() if row["generation"] == str(generation)]
        summary = [
            {
                "candidate_id": row["candidate_id"],
                "accepted": row["accepted"],
                "stage": row["stage"],
                "reason_code": row["reason_code"],
                "screen_score": row["screen_score"],
                "benchmark_score": row["benchmark_score"],
                "fresh_missing_pairs": row["fresh_missing_pairs"],
                "fresh_seed_hits": row["fresh_seed_hits"],
                "fresh_pair_hits": row["fresh_pair_hits"],
                "discriminant_improvements": row["discriminant_improvements"],
                "hypothesis": row["hypothesis"][:500],
            }
            for row in rows
        ]
        workspace = self.candidate_root / f"generation-{generation:04d}" / "critic"
        _initialize_readonly_workspace(workspace, "generation critic")
        prompt = json.dumps({
            "role": "Sol generation critic",
            "task": (
                "Diagnose the entire generation. Explain what worked, what failed, and give one concrete "
                "direction for the next lead researcher. Do not infer hidden seeds or hidden pair identities."
            ),
            "winner": winner_id,
            "generation_results": summary,
            "previous_feedback": state.get("generation_feedback"),
        }, sort_keys=True)
        budget.reserve_ai(1)
        response = self.llm.call(
            prompt=prompt,
            cwd=workspace,
            model=self.config.critic_model,
            reasoning=self.config.critic_reasoning,
            sandbox="read-only",
            timeout=min(budget.seconds_left, self.config.ai_seconds),
            schema=CRITIC_SCHEMA,
        )
        budget.add_usage(response.usage)
        state["generation_feedback"] = response.data
        self.store.save_state(state)
        self.store.append_history(
            "generation_critic", {"generation": generation, "winner": winner_id, "feedback": response.data}, session_id=session_id
        )
        self._say(f"generation {generation}: critic feedback saved for next generation")

    def _generation(self, state: dict, budget: Budget, session_id: str, public_seen: set[str]) -> None:
        generation = state["next_generation"]
        if budget.ai_left < self.config.minimum_generation_ai_calls:
            raise ResearchStop(
                "ai_budget_insufficient_for_generation",
                f"needed_at_least={self.config.minimum_generation_ai_calls}:left={budget.ai_left}",
            )
        generation_dir = self.candidate_root / f"generation-{generation:04d}"
        self._cleanup_candidate_workspace()
        generation_dir.mkdir(parents=True, exist_ok=True)
        catalogue_pairs = {
            (entry["galois_group"], int(entry["real_roots"])) for entry in self.store.catalogue().values()
        }
        self._say(
            f"generation {generation}: one Sol researcher -> five parallel Terra implementations"
        )
        generation_usage_before = budget.usage
        generation_ai_before = budget.ai
        generation_sage_before = budget.sage
        winner_id = "incumbent"
        try:
            research, research_usage = self._ask_researcher(state, budget, generation_dir)
            self.store.append_history(
                "generation_research",
                {
                    "generation": generation,
                    "thesis": research["generation_thesis"],
                    "hypotheses": research["hypotheses"],
                },
                session_id=session_id,
            )
            candidates = self._parallel_implement(research["hypotheses"], budget, generation_dir)
            survivors = self._screen_candidates(candidates, budget, catalogue_pairs)
            if survivors:
                survivors = self._benchmark_candidates(survivors, budget)
            if survivors:
                finalists, incumbent_prelim = self._preliminary_race(
                    survivors,
                    generation=generation,
                    budget=budget,
                    public_seen=public_seen,
                    catalogue_pairs=catalogue_pairs,
                )
            else:
                finalists, incumbent_prelim = [], {"_fresh_seed_pair_counts": {}}

            synthesis = self._synthesize(
                finalists,
                generation=generation,
                budget=budget,
                generation_dir=generation_dir,
                catalogue_pairs=catalogue_pairs,
            )
            challengers = list(finalists)
            if synthesis is not None and synthesis.get("status") == "synthesis_passed":
                challengers.append(synthesis)

            winner, incumbent_final, final_candidates = self._final_race(
                challengers,
                generation=generation,
                budget=budget,
                public_seen=public_seen,
                catalogue_pairs=catalogue_pairs,
            )

            solver_commit = ""
            if winner is not None:
                atomic_text(self.solver_file, winner["source"])
                if solver_sha256(self.solver_file) != winner["hash"]:
                    raise ResearchStop("accepted_solver_copy_hash_mismatch")
                solver_commit = commit_paths(
                    self.root,
                    f"research: accept generation {generation} candidate {winner['id']}",
                    ["mini_igp8/solver.py"],
                ) or ""
                if not solver_commit:
                    raise ResearchStop("accepted_solver_not_committed")
                state["accepted_solver_commit"] = solver_commit
                state["incumbent_solver_hash"] = solver_sha256(self.solver_file)
                state["incumbent_benchmark"] = _metric_summary(winner["benchmark"])
                state["last_solver_change_at"] = state["search_candidates_total"]
                self.store.save_state(state)
                winner_id = winner["id"]
                self._say(f"generation {generation}: ACCEPTED candidate {winner_id} ({winner.get('final_reason')})")
            else:
                self._say(f"generation {generation}: incumbent retained")

            recorded: set[str] = set()
            for candidate in candidates:
                self._record_candidate(
                    candidate,
                    generation=generation,
                    session_id=session_id,
                    accepted=(winner is candidate),
                    solver_commit=solver_commit if winner is candidate else "",
                )
                recorded.add(candidate["id"])
            if synthesis is not None and synthesis["id"] not in recorded:
                self._record_candidate(
                    synthesis,
                    generation=generation,
                    session_id=session_id,
                    accepted=(winner is synthesis),
                    solver_commit=solver_commit if winner is synthesis else "",
                )

            state["next_generation"] += 1
            self.store.save_state(state)
            self.store.append_history(
                "generation_completed",
                {
                    "generation": generation,
                    "winner": winner_id,
                    "ai_calls": budget.ai - generation_ai_before,
                    "sage_calls": budget.sage - generation_sage_before,
                    "token_usage": self._usage_delta(budget.usage, generation_usage_before).__dict__,
                    "final_incumbent": _metric_summary(incumbent_final),
                },
                session_id=session_id,
            )
            self.store.rebuild_report()
            self._critic(state, budget, session_id, generation, winner_id)
        finally:
            self._cleanup_candidate_workspace()

    def _complete_new_pair_discriminants(
        self,
        pair_keys: tuple[str, ...],
        *,
        budget: Budget,
        session_id: str,
    ) -> None:
        for pair_key in pair_keys:
            if budget.seconds_left <= 0:
                return
            entry = self.store.catalogue()[pair_key]
            if entry.get("field_discriminant") is not None:
                continue
            try:
                value = self.field_discriminant_fn(
                    entry["coefficients"],
                    timeout_seconds=min(self.config.verification_seconds, budget.seconds_left),
                )
                budget.spend_sage(1)
            except VerificationTimeoutError:
                self.store.append_history("field_discriminant_timeout", {"pair": pair_key}, session_id=session_id)
            except Exception as exc:
                self.store.append_history(
                    "field_discriminant_error",
                    {"pair": pair_key, "reason_code": type(exc).__name__},
                    session_id=session_id,
                )
            else:
                self.store.set_new_pair_field_discriminant(pair_key, abs(int(value)))

    def _improve_known_discriminants(
        self,
        records: list[dict],
        *,
        excluded_new_pairs: set[str],
        solver_commit: str | None,
        source_event: str,
        state: dict,
        budget: Budget,
        session_id: str,
    ) -> int:
        limit = self.config.discriminant_checks_per_batch
        if limit <= 0:
            return 0
        catalogue = self.store.catalogue()
        best_by_pair: dict[str, dict] = {}
        for record in records:
            if record.get("status") != "verified":
                continue
            key = self.store.pair_key(record["galois_group"], int(record["real_roots"]))
            if key in excluded_new_pairs or key not in catalogue:
                continue
            current_poly = catalogue[key].get("polynomial_discriminant")
            if current_poly is not None and int(record["polynomial_discriminant"]) >= int(current_poly):
                continue
            previous = best_by_pair.get(key)
            if previous is None or int(record["polynomial_discriminant"]) < int(previous["polynomial_discriminant"]):
                best_by_pair[key] = record
        def priority(item: tuple[str, dict]) -> float:
            key, record = item
            old = catalogue[key].get("field_discriminant")
            if old is None:
                return 0.0
            return int(record["polynomial_discriminant"]) / max(1, int(old))
        selected = sorted(best_by_pair.items(), key=priority)[:limit]
        improvements = 0
        for key, record in selected:
            if budget.seconds_left <= 0:
                break
            try:
                value = record.get("field_discriminant")
                if value is None:
                    value = self.field_discriminant_fn(
                        record["coefficients"],
                        timeout_seconds=min(self.config.verification_seconds, budget.seconds_left),
                    )
                budget.spend_sage(1)
                change = self.store.replace_best_if_smaller(
                    key,
                    coefficients=list(record["coefficients"]),
                    polynomial_discriminant=int(record["polynomial_discriminant"]),
                    field_discriminant=abs(int(value)),
                    solver_commit=solver_commit,
                    source_event=source_event,
                )
            except Exception as exc:
                self.store.append_history(
                    "discriminant_improvement_check_error",
                    {"pair": key, "reason_code": type(exc).__name__},
                    session_id=session_id,
                )
                continue
            if change.improved:
                improvements += 1
                state["discriminant_improvements_total"] += 1
                self.store.append_history(
                    "field_discriminant_improved",
                    {
                        "pair": key,
                        "old": change.old_value,
                        "new": change.new_value,
                        "solver_commit": solver_commit,
                    },
                    session_id=session_id,
                )
        return improvements

    def run(self, *, dry_run: bool = False) -> dict:
        if dry_run:
            state = self.store.state()
            self._check_state_consistency(state)
            return self.snapshot()

        lock_path = research_lock_path(self.root)
        with lock_path.open("a+") as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ResearchStop("research_already_running") from exc

            self._cleanup_candidate_workspace()
            state = self.store.state()
            self._check_state_consistency(state)
            _safe_working_tree(self.root)
            self.run_tests(self.root)
            self._validate_solver(self.solver_file)
            ensure_sage_available()
            self._ensure_run_identity(state)

            session_id = uuid.uuid4().hex[:12]
            budget = Budget(self.config, time.monotonic())
            stop_code = "completed"
            self.store.append_history("session_started", {}, session_id=session_id)
            self._say(
                f"session {session_id}: run={state['run_id']} search={state['search_candidates_total']} "
                f"catalogue={len(self.store.catalogue())}/157"
            )
            try:
                self._ensure_baseline(state, budget, session_id)
                seen = self.store.seen_hashes()
                while budget.seconds_left > 0:
                    if len(self.store.catalogue()) == 157 and not self.config.continue_after_full_coverage:
                        stop_code = "all_targets_found"
                        break

                    anchor = max(state["last_new_pair_at"], state["last_solver_change_at"])
                    plateau = state["search_candidates_total"] - anchor >= self.config.stagnation
                    if plateau:
                        if budget.ai_left < self.config.minimum_generation_ai_calls:
                            stop_code = "ai_budget_insufficient_for_generation"
                            break
                        self._say(
                            f"plateau: {state['search_candidates_total'] - anchor} search candidates "
                            f"without a new pair/solver change; starting generation {state['next_generation']}"
                        )
                        self._generation(state, budget, session_id, seen)
                        continue

                    request = self.config.batch_size
                    batch = state["next_search_batch"]
                    seed = search_seed(self.config.search_master_seed, batch)
                    self._say(f"search batch {batch}: up to {request} unseen candidates")
                    summary, records, hashes = evaluate_search_batch(
                        self.solver_file,
                        seed=seed,
                        budget=request,
                        oversample_factor=self.config.search_oversample,
                        already_seen=seen,
                        solver_seconds=self.config.solver_seconds,
                        verification_seconds=self.config.verification_seconds,
                        verifier=self.verifier,
                        deadline=budget.deadline,
                        progress=self._stage_progress(f"search batch {batch}"),
                        progress_every=self.config.progress_every,
                    )
                    budget.spend_sage(summary["sage_calls"])
                    event = self.store.append_history(
                        "search_batch", {"batch": batch, "seed": seed, **summary}, session_id=session_id
                    )
                    change = self.store.update_catalogue(
                        records,
                        solver_commit=state["accepted_solver_commit"],
                        source_event=event,
                    )
                    self.store.add_seen_hashes(hashes, known=seen, max_entries=self.config.recent_hash_limit)
                    state["search_candidates_total"] += summary["submitted"]
                    state["next_search_batch"] += 1
                    if change.new_pairs:
                        state["last_new_pair_at"] = state["search_candidates_total"]
                    self._complete_new_pair_discriminants(
                        change.new_pairs, budget=budget, session_id=session_id
                    )
                    disc_improvements = self._improve_known_discriminants(
                        records,
                        excluded_new_pairs=set(change.new_pairs),
                        solver_commit=state["accepted_solver_commit"],
                        source_event=event,
                        state=state,
                        budget=budget,
                        session_id=session_id,
                    )
                    self.store.save_state(state)
                    self.store.rebuild_report()
                    self._say(
                        f"search batch {batch}: checked={summary['submitted']}, "
                        f"new_pairs={len(change.new_pairs)}, disc_improvements={disc_improvements}, "
                        f"catalogue={len(self.store.catalogue())}/157, elapsed={summary['elapsed_seconds']:.1f}s"
                    )
                    if summary["deadline_reached"]:
                        stop_code = "wall_time_limit_reached"
                        break
                    if summary["submitted"] == 0:
                        stop_code = "solver_produced_no_unseen_candidates"
                        break

                if budget.seconds_left <= 0:
                    stop_code = "wall_time_limit_reached"
            except EvaluationDeadlineExceeded:
                stop_code = "wall_time_limit_reached"
            except ResearchStop as exc:
                stop_code = exc.code
                if exc.detail:
                    self.store.append_history(
                        "research_stop_detail", {"code": exc.code, "detail": exc.detail}, session_id=session_id
                    )
            except (SolverError, CodexFailure) as exc:
                stop_code = "research_infrastructure_failure"
                detail = str(exc)
                self._say(f"research infrastructure failure: {detail}")
                self.store.append_history(
                    "research_infrastructure_failure", {"detail": detail}, session_id=session_id
                )
            finally:
                self._cleanup_candidate_workspace()
                state["last_stop_code"] = stop_code
                self.store.save_state(state)
                self.store.rebuild_report()
                self.store.append_history(
                    "session_finished",
                    {
                        "stop_code": stop_code,
                        "sage_calls": budget.sage,
                        "ai_calls": budget.ai,
                        "token_usage": budget.usage.__dict__,
                    },
                    session_id=session_id,
                )
                try:
                    commit_paths(
                        self.root,
                        "research: checkpoint results",
                        [f"results/{name}" for name in RESULT_FILENAMES],
                    )
                except GitError as exc:
                    raise ResearchStop("git_checkpoint_failed", str(exc)) from exc
            return {
                "session_id": session_id,
                "stop_code": stop_code,
                **self.snapshot(),
                "sage_calls_this_session": budget.sage,
                "ai_calls_this_session": budget.ai,
                "token_usage_this_session": budget.usage.__dict__,
            }

    def snapshot(self) -> dict:
        state = self.store.state()
        catalogue = self.store.catalogue()
        anchor = max(state["last_new_pair_at"], state["last_solver_change_at"])
        return {
            "run_id": state.get("run_id"),
            "catalogue_pairs": len(catalogue),
            "catalogue_groups": len({entry["galois_group"] for entry in catalogue.values()}),
            "target_pairs": 157,
            "target_groups": 50,
            "recent_seen_candidates": len(self.store.seen_hashes()),
            "search_candidates_total": state["search_candidates_total"],
            "candidates_since_discovery_or_solver_change": state["search_candidates_total"] - anchor,
            "next_generation": state["next_generation"],
            "next_search_batch": state["next_search_batch"],
            "accepted_solver_commit": state["accepted_solver_commit"],
            "incumbent_benchmark": state.get("incumbent_benchmark"),
            "discriminant_improvements_total": state["discriminant_improvements_total"],
            "last_stop_code": state.get("last_stop_code"),
        }
