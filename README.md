# Mini-IGP8 Optimized Parallel Experiment (v6)

Autonomous search for explicit degree-8 integer polynomials covering all 157 target `(8Tn, r)` pairs. Finding missing pairs is the primary objective; improving the smallest known absolute number-field discriminant for solved pairs is a secondary public-search objective.

## Runtime design

Normal search runs in **10,000-candidate batches**. After **50,000 public search candidates** without a new pair or accepted solver, one research generation begins:

1. one Sol researcher proposes five genuinely different hypotheses;
2. five Terra implementers update persistent candidate lineages A-E concurrently;
3. all five receive a 500-slot viability screen; at most three survive;
4. survivors enter a cheap **5 + 10 seed** shared-seed qualifier; only the best two continue;
5. only those two pay the 2,000-slot frozen benchmark;
6. Sol may synthesize the two finalists and Terra updates persistent candidate S;
7. the expensive final holdout tests only **best solo vs synthesis vs incumbent** for 20 seeds, then only the single strongest challenger vs incumbent for another 40 seeds;
8. only the final winner may replace `mini_igp8/solver.py`;
9. Sol critic records generation-level lessons for the next researcher.

This keeps the strong **60-seed final acceptance test** while removing most redundant preliminary Sage work.

## Main performance changes from v5.x

- Search oversampling is `1`, so a 10,000-candidate batch no longer blindly generates 20,000-40,000 raw candidates.
- Public 10k solver generation has its own 120-second timeout; candidate quality is still judged against the stricter 2,000-candidate / 30-second contract.
- Frozen benchmarks are delayed until after the cheap qualifier.
- Preliminary comparison shrank from 60 seeds to 15; the final acceptance race remains 60 seeds.
- The final race carries only one challenger into its last 40 seeds.
- Hidden screen/benchmark/race verification skips polynomial-discriminant computation.
- Exact Sage verification uses a persistent **4-process worker pool** by default. Change `verification_workers` in `config.toml` if RAM/CPU suggests a different value.
- `mini-igp8 research` no longer reruns the full unit suite on every invocation. `mini-igp8 check` remains the explicit validation command.
- Solver contract validation always stress-tests 2,000 candidates instead of scaling with the 10k search batch.
- Timing logs now separate solver-generation time from Sage-verification time.

A worst-case generation is roughly **28k hidden Sage candidate verifications** before early failures/pruning, instead of roughly 50k-60k in the previous tournament design.

## Candidate persistence

`candidates/current/` contains persistent lineages:

```text
candidate-A/solver.py
candidate-B/solver.py
candidate-C/solver.py
candidate-D/solver.py
candidate-E/solver.py
candidate-S/solver.py
```

Normal research never deletes them. Terra continues its previous lineage rather than starting from scratch each generation. Invalid implementations are rolled back. Only `mini-igp8 new-run --yes` deletes the candidate workspace and restores the naive baseline.

The main repository stays clean because `/candidates/current/` is Git-ignored; the accepted incumbent alone lives at `mini_igp8/solver.py`.

## Discriminants

Public search computes polynomial discriminants because they cheaply prefilter potential field-discriminant improvements. New pairs always receive an exact number-field discriminant. For already-solved pairs, at most four promising pairs per 10k search batch receive an exact field-discriminant check.

Discriminant improvements do **not** reset the 50,000-candidate plateau. Hidden tournament samples do not spend time optimizing discriminants.

The catalogue preserves first-discovery and current-best provenance separately.

## Commands

```bash
python -m pip install -e .
mini-igp8 check
mini-igp8 status
mini-igp8 research
```

Resume uses the same run, catalogue, accepted solver, candidate lineages and history.

A destructive clean slate is explicit:

```bash
mini-igp8 new-run --yes
```

## Default controls

- public search batch: 10,000 candidates;
- AI plateau: 50,000 stagnant public candidates;
- Sage-call count: uncapped telemetry only;
- Sage verification workers: 4;
- AI calls/session: 45;
- session wall time: 360 minutes;
- Terra implementations: 5 in parallel;
- candidate contract: 2,000 candidates within 30 seconds;
- public 10k generation timeout: 120 seconds.

If `verification_workers = 4` causes memory pressure, try 2. If Sage is CPU-bound and the machine has ample RAM/cores, try 6 and compare the new timing logs rather than assuming more workers is always faster.

## Durable files

The six result files remain stable:

```text
results/catalogue.jsonl
results/experiments.csv
results/history.jsonl
results/report.md
results/seen_hashes.txt
results/state.json
```

`experiments.csv` and `history.jsonl` remain append-only for a run. `seen_hashes.txt` is only a rolling duplicate cache.
