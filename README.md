# Mini-IGP8 Parallel Research Experiment

A clean-slate autonomous experiment for finding explicit degree-8 integer polynomials for all
157 target `(8Tn, r)` inverse-Galois pairs, while secondarily improving the smallest known
absolute number-field discriminants for already-solved pairs.

## Core idea

The repository starts with an intentionally poor random solver. Normal search runs until 5,000
search candidates pass without a new target pair or accepted solver. A research **generation**
then runs:

1. **One Sol lead researcher** proposes exactly five deliberately different hypotheses.
2. **Five Terra implementers run concurrently**, each editing its own isolated solver under
   `candidates/current/`.
3. Every candidate gets a 500-slot hidden viability screen.
4. At most the best three survivors receive the 2,000-slot frozen benchmark and an adaptive
   10 -> 30 -> 60 shared-seed preliminary race against the incumbent.
5. If at least two candidates pass, **Sol synthesizes** their complementary mechanisms and a
   **Terra synthesis implementer** creates one coherent combined solver.
6. Solo finalists and the synthesis candidate enter a separate fresh holdout race: 20 shared
   seeds, then another 40 for the strongest two challengers.
7. Only the final winner may replace `mini_igp8/solver.py`; it is committed to Git.
8. **Sol critic runs after every completed generation**, accepted or rejected, and its feedback
   is fed to the next generation.

A failed generation does **not** force another 5,000-candidate wait. The controller immediately
starts another generation while the session has enough AI budget. An accepted solver gets a new
5,000-candidate search window.

## Objectives

Selection is lexicographic:

1. distinct currently-missing target pairs found;
2. consistency across independent fresh seeds;
3. total missing-pair hits / paired-seed wins;
4. exact field-discriminant improvements for already-solved pairs;
5. frozen benchmark quality.

Thus one genuinely new `(8Tn,r)` remains more valuable than many easy discriminant reductions.
After 157/157 is reached, the default configuration keeps running so the experiment can continue
to improve field discriminants.

### Discriminant work during normal search

The hot verifier does not compute a number-field discriminant for every polynomial. New pairs
always get an exact field discriminant. For already-solved pairs, each 1,000-candidate search
batch considers only candidates whose **polynomial** discriminant improves the current
representative, keeps at most one candidate per pair, and performs at most 8 exact field-
discriminant checks. A genuine improvement replaces only the best representative.

The catalogue preserves both:

- `first_solver_commit`: solver that first solved the pair;
- `best_solver_commit`: solver that found the current smallest field-discriminant representative.

Discriminant improvements do not reset the plateau counter.

## Repository layout

```text
mini-igp8-experiment/
├── mini_igp8/
│   ├── baseline_solver.py     # intentionally bad clean-slate generator
│   ├── solver.py              # only accepted incumbent
│   ├── research.py            # generation controller
│   ├── evaluator.py
│   ├── verifier.py
│   ├── storage.py
│   └── ...
├── candidates/
│   ├── README.md
│   └── current/               # runtime only, Git-ignored, auto-deleted
├── results/                   # exactly six durable files
├── data/targets.json
├── tests/
└── config.toml
```

`candidates/current/` contains at most one active generation. It is removed after a generation
and automatically cleaned on the next session after a crash. No `solver_v17.py`, run folders,
proposal archives, worktrees, or agent-created notes accumulate.

## Durable history

The six result files are:

```text
results/catalogue.jsonl
results/experiments.csv
results/history.jsonl
results/report.md
results/seen_hashes.txt
results/state.json
```

`experiments.csv` and `history.jsonl` are append-only for the lifetime of one run. Earlier solver
experiments are never deleted when a later solver is accepted. `report.md` now displays the
**complete** solver experiment table instead of only the last ten rows.

`seen_hashes.txt` is intentionally different: it is only a rolling duplicate-prevention window,
not scientific history, and is bounded to 250,000 hashes.

## Clean slate vs resume

Install and validate:

```bash
python -m pip install -e .
mini-igp8 check
mini-igp8 status
```

Start or resume the same run:

```bash
mini-igp8 research
```

A new session resumes the same catalogue, accepted solver, generation critic feedback, search
cursor, and complete history.

Destroy the current experiment and return to the intentionally poor baseline:

```bash
mini-igp8 new-run --yes
```

A new run has an empty catalogue/history/seen set and `solver.py == baseline_solver.py`.

## Default resource controls

- Sage calls: **uncapped**; counted only as telemetry.
- Sage verification workers: **6 total**. Each evaluation batch uses at most
  six independent Sage processes; this is one global batch limit, not six
  processes for each of A--E and S simultaneously.
- AI calls/session: 45.
- Wall time/session: 360 minutes.
- One full generation normally uses 9 AI calls:
  - 1 Sol lead research;
  - 5 parallel Terra implementations;
  - 1 Sol synthesis + 1 Terra synthesis when >=2 finalists survive;
  - 1 Sol generation critic.

With 45 calls, a session can usually complete about three full synthesis generations, with spare
budget for partial cases. Increase this operational limit in `config.toml` if desired; it is not
part of the mathematical acceptance criterion.

## Important experimental hygiene

Hidden screening/benchmark/fresh evidence never enters the public catalogue. Hidden seed values
and hidden target identities from evaluation are not shown to Sol/Terra. Only normal search can
claim a public discovery or improve a public discriminant record.
