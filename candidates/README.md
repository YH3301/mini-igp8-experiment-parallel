# Persistent candidate lineages

`mini-igp8 research` maintains up to six Git-ignored workspaces under `candidates/current/`:

- `candidate-A` through `candidate-E`: the five persistent Terra lineages;
- `candidate-S`: the persistent synthesis lineage.

Normal generations update these same `solver.py` files in place. Successful implementations are checkpointed in each candidate's small nested Git repository; invalid edits are rolled back. The main repository still contains only the accepted incumbent at `mini_igp8/solver.py`.

Only `mini-igp8 new-run --yes` deletes `candidates/current/`.
