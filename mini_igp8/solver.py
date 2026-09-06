"""A deterministic portfolio of structured, monic degree-eight polynomials.

The output is deliberately organized around permutation geometry rather than a
generic coefficient box. Coefficients are in ascending order.
"""

from __future__ import annotations

from fractions import Fraction


_MASK64 = (1 << 64) - 1
_WEIGHTS = (15, 10, 15, 15, 15, 15, 15)
# g(q), reciprocal lift, Q(h), quadratic iterate, Dickson, sparse, Eisenstein
_SHELLS = (3, 5, 8, 12)


def _mix64(value: int) -> int:
    """Stable counter mixer, independent of Python's hash randomization."""
    value = (value + 0x9E3779B97F4A7C15) & _MASK64
    value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & _MASK64
    value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & _MASK64
    return value ^ (value >> 31)


def _word(seed: int, lane: int, counter: int, coordinate: int) -> int:
    value = seed & _MASK64
    value ^= (lane + 1) * 0xD1B54A32D192ED03
    value ^= (counter + 1) * 0x94D049BB133111EB
    value ^= (coordinate + 1) * 0xBF58476D1CE4E5B9
    return _mix64(value)


def _signed(seed: int, lane: int, counter: int, coordinate: int, shell: int) -> int:
    return _word(seed, lane, counter, coordinate) % (2 * shell + 1) - shell


def _multiply(left: list[int], right: list[int]) -> list[int]:
    product = [0] * (len(left) + len(right) - 1)
    for i, a in enumerate(left):
        for j, b in enumerate(right):
            product[i + j] += a * b
    return product


def _compose(outer: list[int], inner: list[int]) -> list[int]:
    result = [outer[-1]]
    for coefficient in reversed(outer[:-1]):
        result = _multiply(result, inner)
        result[0] += coefficient
    return result


def _value(coefficients: list[int], x: int) -> int:
    result = 0
    for coefficient in reversed(coefficients):
        result = result * x + coefficient
    return result


def _usable(coefficients: list[int]) -> bool:
    """Reject only cheap degeneracies; thin exceptional loci stay available."""
    return (
        len(coefficients) == 9
        and coefficients[0] != 0
        and coefficients[-1] == 1
        and all(_value(coefficients, root) != 0 for root in (-2, -1, 1, 2))
    )


def _general_two(seed: int, counter: int, shell: int) -> list[int]:
    """g(q(x)): four natural blocks of size two."""
    u = _signed(seed, 0, counter, 0, shell)
    v = _signed(seed, 0, counter, 1, shell)
    outer = [_signed(seed, 0, counter, index + 2, shell) for index in range(4)]
    return _compose(outer + [1], [v, u, 1])


def _reciprocal(seed: int, counter: int, shell: int) -> list[int]:
    """x^4 h(x+x^-1), a reciprocal size-two-block sublocus."""
    c0, c1, c2, c3 = (
        _signed(seed, 1, counter, coordinate, shell) for coordinate in range(4)
    )
    return [1, c3, 4 + c2, 3 * c3 + c1, 6 + 2 * c2 + c0,
            3 * c3 + c1, 4 + c2, c3, 1]


def _four_blocks(seed: int, counter: int, shell: int) -> list[int]:
    """Q(h(x)): two natural blocks of size four."""
    d, c, b, linear, constant = (
        _signed(seed, 2, counter, coordinate, shell) for coordinate in range(5)
    )
    # Trace-normalising h makes this orientation distinct without large shifts.
    return _compose([constant, linear, 1], [d, c, b, 0, 1])


def _nested(seed: int, counter: int, shell: int) -> list[int]:
    """The third iterate of a quadratic map, minus a target."""
    u = _signed(seed, 3, counter, 0, shell)
    v = _signed(seed, 3, counter, 1, shell)
    target = _signed(seed, 3, counter, 2, shell * shell + 2)
    polynomial = [0, 1]
    for _ in range(3):
        polynomial = _compose([v, u, 1], polynomial)
    polynomial[0] -= target
    return polynomial


def _dickson(seed: int, counter: int, shell: int) -> list[int]:
    """D_8(x,a) plus controlled affine perturbations."""
    a = _signed(seed, 4, counter, 0, shell)
    previous, current = [2], [0, 1]
    for _ in range(2, 9):
        following = [0] + current
        for index, coefficient in enumerate(previous):
            following[index] -= a * coefficient
        previous, current = current, following
    current[0] += _signed(seed, 4, counter, 1, 2 * shell)
    current[1] += _signed(seed, 4, counter, 2, 2 * shell)
    return current


def _sparse(seed: int, counter: int, shell: int) -> list[int]:
    """Three- and four-term low-height octics cycling support patterns."""
    first = 1 + counter % 7
    second = 1 + (_word(seed, 5, counter, 0) % 7)
    if second == first:
        second = second % 7 + 1
    coefficients = [_signed(seed, 5, counter, 1, shell) or 1] + [0] * 7 + [1]
    coefficients[first] = _signed(seed, 5, counter, 2, 2 * shell) or 1
    if counter % 3:
        coefficients[second] = _signed(seed, 5, counter, 3, shell) or -1
    return coefficients


def _not_divisible(seed: int, counter: int, coordinate: int, prime: int, shell: int) -> int:
    value = _signed(seed, 6, counter, coordinate, shell)
    if value == 0 or value % prime == 0:
        value = 1 if (_word(seed, 6, counter, coordinate + 20) & 1) else -1
    return value


def _eisenstein(seed: int, counter: int, shell: int) -> list[int]:
    """Low-height dense, alternating, and sparse shapes, Eisenstein at p."""
    prime = (2, 3, 5)[counter % 3]
    shape = (counter // 3) % 3
    interior = [0] * 6
    if shape == 0:
        interior = [_signed(seed, 6, counter, i, shell) for i in range(6)]
    elif shape == 1:
        for i in range(6):
            magnitude = abs(_signed(seed, 6, counter, i, shell))
            interior[i] = magnitude if i % 2 == 0 else -magnitude
    else:
        for offset in range(2 + (counter & 1)):
            index = (_word(seed, 6, counter, 10 + offset) + offset) % 6
            interior[index] = _not_divisible(seed, counter, 16 + offset, prime, shell)
    trace = 0 if counter % 7 else _not_divisible(seed, counter, 30, prime, shell)
    return [prime * _not_divisible(seed, counter, 31, prime, shell)] + [
        prime * value for value in interior
    ] + [prime * trace, 1]


def _trim(poly: list[Fraction]) -> list[Fraction]:
    while len(poly) > 1 and not poly[-1]:
        poly.pop()
    return poly


def _remainder(dividend: list[Fraction], divisor: list[Fraction]) -> list[Fraction]:
    remainder = dividend[:]
    while len(remainder) >= len(divisor):
        scale = remainder[-1] / divisor[-1]
        offset = len(remainder) - len(divisor)
        for index, coefficient in enumerate(divisor):
            remainder[index + offset] -= scale * coefficient
        _trim(remainder)
    return remainder


def _real_root_count(coefficients: list[int]) -> int:
    """Exact Sturm count, used only by the small Eisenstein lane."""
    first = [Fraction(value) for value in coefficients]
    derivative = [Fraction(i) * first[i] for i in range(1, len(first))]
    sturm = [_trim(first), _trim(derivative)]
    while len(sturm[-1]) > 1:
        sturm.append(_trim([-value for value in _remainder(sturm[-2], sturm[-1])]))

    def variations(positive: bool) -> int:
        signs = []
        for polynomial in sturm:
            sign = 1 if polynomial[-1] > 0 else -1
            if not positive and (len(polynomial) - 1) % 2:
                sign = -sign
            signs.append(sign)
        return sum(left != right for left, right in zip(signs, signs[1:]))

    return variations(False) - variations(True)


_GENERATORS = (_general_two, _reciprocal, _four_blocks, _nested, _dickson, _sparse, _eisenstein)


def _quotas(budget: int) -> list[int]:
    """Largest-remainder allocation for the 15/10/15/... portfolio."""
    total = sum(_WEIGHTS)
    quotas = [budget * weight // total for weight in _WEIGHTS]
    remainder = budget - sum(quotas)
    order = sorted(range(len(_WEIGHTS)), key=lambda i: (-(budget * _WEIGHTS[i] % total), i))
    for lane in order[:remainder]:
        quotas[lane] += 1
    return quotas


def _schedule(seed: int, budget: int) -> list[int]:
    """Spread exact quotas evenly; seed-keyed ties diversify every prefix."""
    quotas = _quotas(budget)
    used = [0] * len(quotas)
    order: list[int] = []
    for position in range(budget):
        best = max(
            range(len(quotas)),
            key=lambda lane: (
                (position + 1) * quotas[lane] - used[lane] * budget,
                _word(seed, 20 + position // 7, lane, position),
            ),
        )
        used[best] += 1
        order.append(best)
    return order


def _score(coefficients: list[int], support_seen: set[tuple[int, ...]]) -> int:
    """A deliberately local low-height proxy, never a cross-lane ranking."""
    height = max(abs(value) for value in coefficients[:-1])
    mass = sum(abs(value) for value in coefficients[:-1])
    support = tuple(i for i, value in enumerate(coefficients[:-1]) if value)
    return height * 64 + mass + (17 if support in support_seen else 0)


def _fallback_eisenstein(serial: int) -> list[int]:
    """Injective, unmistakably Eisenstein backstop for pathological collisions."""
    return [2 * (2 * serial + 1), 0, 0, 0, 0, 0, 2 * (1_000_000 + serial), 0, 1]


def generate_candidates(seed: int, budget: int) -> list[list[int]]:
    """Return exactly ``budget`` unique structured monic octics."""
    if isinstance(budget, bool) or not isinstance(budget, int):
        raise TypeError("budget must be an integer")
    if budget < 0:
        raise ValueError("budget must be nonnegative")

    counters = [0] * len(_GENERATORS)
    seen: set[tuple[int, ...]] = set()
    support_seen: set[tuple[int, ...]] = set()
    output: list[list[int]] = []

    for position, primary in enumerate(_schedule(seed, budget)):
        # Only the overlapping size-two constructions spill into one another.
        lanes = (primary, 1 - primary) if primary in (0, 1) else (primary,)
        proposals: list[list[int]] = []
        for lane in lanes:
            for attempt in range(4):
                counter = counters[lane]
                counters[lane] += 1
                proposal = _GENERATORS[lane](seed, counter, _SHELLS[attempt])
                if not _usable(proposal) or tuple(proposal) in seen:
                    continue
                if lane == 6:
                    desired = (0, 2, 4, 6)[position % 4]
                    if _real_root_count(proposal) != desired and attempt < 3:
                        continue
                proposals.append(proposal)
            if proposals:
                break

        if proposals:
            accepted = min(proposals, key=lambda item: _score(item, support_seen))
        else:
            accepted = _fallback_eisenstein(position + 1)

        seen.add(tuple(accepted))
        support_seen.add(tuple(i for i, value in enumerate(accepted[:-1]) if value))
        output.append(accepted)
    return output
