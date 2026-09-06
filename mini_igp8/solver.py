"""Canonical clean-slate solver copied by ``mini-igp8 reset --yes``.

This is intentionally naive.  It samples unrelated small-coefficient monic
integer octics, so it overwhelmingly finds generic groups and gives the research
loop plenty of room to improve.
"""

from __future__ import annotations

import random


COEFFICIENT_BOUND = 20


def generate_candidates(seed: int, budget: int) -> list[list[int]]:
    """Return exactly ``budget`` unique deterministic random monic octics."""

    if isinstance(budget, bool) or not isinstance(budget, int):
        raise TypeError("budget must be an integer")
    if budget < 0:
        raise ValueError("budget must be nonnegative")

    rng = random.Random(seed)
    candidates: list[list[int]] = []
    seen: set[tuple[int, ...]] = set()
    while len(candidates) < budget:
        coefficients = [rng.randint(-COEFFICIENT_BOUND, COEFFICIENT_BOUND) for _ in range(8)] + [1]
        if coefficients[0] == 0:
            continue
        key = tuple(coefficients)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(coefficients)
    return candidates
