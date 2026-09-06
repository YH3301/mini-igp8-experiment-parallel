# Candidate workspace

`mini-igp8 research` creates at most one active generation under `candidates/current/`.
The five Terra implementations, synthesis workspace, and temporary metadata live there.
`candidates/current/` is ignored by Git and is deleted after every completed generation.
If a process crashes, the next research session removes the stale workspace before starting a
new generation. Only the final accepted winner is copied into `mini_igp8/solver.py` and committed.
