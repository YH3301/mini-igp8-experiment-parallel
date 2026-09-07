# Mini-IGP8 agent rules

This repository is an autonomous mathematical experiment, not a general coding workspace.

## Experiment invariants

1. A new run starts with empty results and `mini_igp8/solver.py == mini_igp8/baseline_solver.py`.
2. Public discoveries are cumulative. Later solver changes never invalidate earlier Sage-verified pairs.
3. Missing target-pair discovery is the primary objective. Smaller absolute number-field discriminants for solved pairs are secondary.
4. Hidden screen/benchmark/race evidence never enters the public catalogue and hidden seed identities are never exposed to agents.
5. Only a final accepted winner may replace `mini_igp8/solver.py`.
6. `results/experiments.csv` and `results/history.jsonl` are append-only during a run.
7. `results/seen_hashes.txt` is only a bounded duplicate cache.

## Persistent candidate lineages

The controller owns these Git-ignored workspaces:

`candidates/current/candidate-A` through `candidate-E`, plus `candidate-S` for synthesis.

They persist across normal generations. Terra edits only its own `solver.py`; the controller checkpoints successful edits in each nested candidate Git repository and rolls back invalid implementations. Only `mini-igp8 new-run --yes` deletes the candidate lineages.

Do not create generation folders, solver-version files, notes, logs, worktrees, or other artifacts.

## Solver contract and code quality

`generate_candidates(seed: int, budget: int)` returns exactly `budget` unique deterministic integer vectors `[a0,...,a8]`, with `a8 == 1` and `a0 != 0`. There is no coefficient magnitude or symmetry restriction.

Never hard-code catalogue polynomials, target answers, or held-out seeds. Keep generation fast and bounded. Do not perform Galois-group or number-field computations inside `solver.py`.

Write readable conventional Python. Use descriptive names, normal spacing, small helpers, and brief comments/docstrings for non-obvious mathematical constructions, hashing/mixing routines, or numerical tricks. Do not use code golf, semicolon-chained statements, or compressed multi-statement lines.
