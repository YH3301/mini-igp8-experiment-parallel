# Mini-IGP8 agent rules

This repository is an autonomous mathematical experiment, not a general coding workspace.

## Immutable experiment principles

1. A new run begins with empty results and `mini_igp8/solver.py` identical to
   `mini_igp8/baseline_solver.py`.
2. Normal search discoveries are cumulative and remain valid after later solver changes.
3. Missing target-pair discovery is the primary objective. Smaller absolute number-field
   discriminants for already-solved pairs are secondary.
4. Hidden screening, benchmark, and race evidence must never be inserted into the public
   catalogue or exposed as hidden seed/pair identities to future agents.
5. Only an accepted final-generation winner may replace `mini_igp8/solver.py`.
6. Accepted solver revisions are preserved by Git. Do not create permanent solver-version files.
7. `results/experiments.csv` and `results/history.jsonl` are append-only during a run. Never
   truncate old solver experiments after an acceptance.
8. `results/seen_hashes.txt` is only a bounded duplicate-prevention cache and may roll over.

## Candidate workspaces

The controller owns `candidates/current/`. Five Terra candidates may exist there concurrently.
A candidate agent may edit **only its own `solver.py`**. It must not create files, commit, inspect
siblings, or read parent-repository results. The controller validates each nested workspace and
rejects candidates that change other paths.

The candidate tree is Git-ignored and must be deleted after each completed generation. Stale
work from a crash is removed at the start of the next research session.

## Solver contract

`generate_candidates(seed: int, budget: int)` must return exactly `budget` unique deterministic
coefficient vectors `[a0,...,a8]` with integer entries, `a8 == 1`, and `a0 != 0`. There is no
coefficient magnitude bound and no reciprocal/palindromic requirement.

Never hard-code catalogue polynomials, target answers, or held-out seed values.

### Human-readable solver code

`solver.py` must remain understandable to a human researcher. Optimization does not justify code golf. Use conventional Python formatting, descriptive names, appropriate helper functions, and useful comments/docstrings for mathematical constructions.

Do not use semicolon-separated statements, multiple statements on one line, unnecessarily compressed comprehensions/lambdas, or deliberately minified code. Keep mathematical and performance-sensitive code readable. Prefer simple code over clever code when performance is comparable.
