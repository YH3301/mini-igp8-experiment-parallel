"""Deterministic monic-octic generator with a small controlled tower probe."""
from __future__ import annotations

from fractions import Fraction
from math import gcd, isqrt

MASK = (1 << 64) - 1
PRIMES = (3, 5, 7, 11)
PAIRS = ((2, 3), (2, 5), (3, 5), (2, 7), (3, 7), (5, 6))
TARGET_ROOTS = (8, 6, 8, 0, 8, 4, 6, 2, 8, 6)
SCALE = 10**12
PORTFOLIO_WEIGHTS = (24, 12, 12, 12, 18, 8, 7, 4, 3)
SHELLS = (1, 2, 3, 5, 8)


def _mix(value: int) -> int:
    """SplitMix finalizer gives deterministic, independent-looking lanes."""
    value = (value + 0x9E3779B97F4A7C15) & MASK
    value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & MASK
    value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & MASK
    return value ^ (value >> 31)


def _word(seed: int, lane: int, serial: int, index: int) -> int:
    return _mix((seed & MASK) ^ (lane + 1) * 0xD1B54A32D192ED03 ^
                (serial + 1) * 0x94D049BB133111EB ^
                (index + 1) * 0xBF58476D1CE4E5B9)


def _trim(poly: list[int]) -> list[int]:
    while len(poly) > 1 and poly[-1] == 0:
        poly.pop()
    return poly


def _add(left: list[int], right: list[int]) -> list[int]:
    result = [0] * max(len(left), len(right))
    for index, value in enumerate(left):
        result[index] += value
    for index, value in enumerate(right):
        result[index] += value
    return _trim(result)


def _mul(left: list[int], right: list[int]) -> list[int]:
    result = [0] * (len(left) + len(right) - 1)
    for i, value in enumerate(left):
        for j, other in enumerate(right):
            result[i + j] += value * other
    return _trim(result)


def _tower_product(left: int, right: int, parameters: tuple[int, ...]) -> list[int]:
    """Multiply basis elements where u²=a, v²=b, w²=c in Q(u,v,w)."""
    a, b, c0, c1, c2, c3 = parameters
    exponents = ((left & 1) + (right & 1), ((left >> 1) & 1) + ((right >> 1) & 1),
                 ((left >> 2) & 1) + ((right >> 2) & 1))
    terms = {exponents: 1}
    relations = (((a, 0, 0),), ((b, 0, 0),),
                 ((c0, 0, 0), (c1, 1, 0), (c2, 0, 1), (c3, 1, 1)))
    for level in (2, 1, 0):
        while any(powers[level] >= 2 for powers in terms):
            reduced: dict[tuple[int, int, int], int] = {}
            for powers, coefficient in terms.items():
                if powers[level] < 2:
                    reduced[powers] = reduced.get(powers, 0) + coefficient
                    continue
                base = list(powers)
                base[level] -= 2
                for factor, du, dv in relations[level]:
                    key = (base[0] + du, base[1] + dv, base[2])
                    reduced[key] = reduced.get(key, 0) + coefficient * factor
            terms = reduced
    product = [0] * 8
    for (u_power, v_power, w_power), coefficient in terms.items():
        product[u_power + 2 * v_power + 4 * w_power] += coefficient
    return product


def _tower_characteristic(theta: list[int], parameters: tuple[int, ...]) -> list[int]:
    """Faddeev--LeVerrier characteristic polynomial in the integral basis."""
    matrix = []
    for column_number in range(8):
        column = [0] * 8
        for basis_number, coefficient in enumerate(theta):
            if coefficient:
                product = _tower_product(basis_number, column_number, parameters)
                for row, value in enumerate(product):
                    column[row] += coefficient * value
        matrix.append(column)
    power = [row[:] for row in matrix]
    coefficients = [1]
    for degree in range(1, 9):
        trace = sum(power[i][i] for i in range(8))
        if trace % degree:
            return []
        coefficient = -trace // degree
        coefficients.append(coefficient)
        if degree < 8:
            for i in range(8):
                power[i][i] += coefficient
            power = [[sum(matrix[row][k] * power[k][column] for k in range(8))
                      for column in range(8)] for row in range(8)]
    return list(reversed(coefficients))


def _embedding_intervals(a: int, b: int, triple: tuple[int, int, int]) -> list[tuple[int, int]]:
    """Certified intervals for the four nonconstant real embeddings of c."""
    roots = (isqrt(a * SCALE * SCALE), isqrt(b * SCALE * SCALE),
             isqrt(a * b * SCALE * SCALE))
    intervals = []
    for sign_a, sign_b in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
        total_low = total_high = 0
        for coefficient, signed_root in zip(triple, (sign_a * roots[0], sign_b * roots[1],
                                                      sign_a * sign_b * roots[2])):
            low, high = (signed_root, signed_root + 1) if signed_root >= 0 else (signed_root - 1, signed_root)
            if coefficient < 0:
                low, high = -high, -low
            total_low += coefficient * low
            total_high += coefficient * high
        intervals.append((total_low, total_high))
    return intervals


def _controlled_constant(a: int, b: int, triple: tuple[int, int, int], positives: int) -> int | None:
    """Select integral c0 from a certified interval with the requested signs."""
    ordered = sorted(_embedding_intervals(a, b, triple))
    if any(ordered[i][1] >= ordered[i + 1][0] for i in range(3)):
        return None
    if positives == 0:
        return (-ordered[3][1]) // SCALE
    if positives == 4:
        return (-ordered[0][0]) // SCALE + 1
    lower = -ordered[4 - positives][0]
    upper = -ordered[3 - positives][1]
    candidate = lower // SCALE + 1
    return candidate if candidate * SCALE < upper else None


def _mod(poly: list[int], prime: int) -> list[int]:
    return _trim([coefficient % prime for coefficient in poly])


def _divide(left: list[int], right: list[int], prime: int) -> tuple[list[int], list[int]]:
    left, right = _mod(left[:], prime), _mod(right[:], prime)
    quotient = [0] * max(1, len(left) - len(right) + 1)
    inverse = pow(right[-1], -1, prime)
    while len(left) >= len(right) and left != [0]:
        offset = len(left) - len(right)
        factor = left[-1] * inverse % prime
        quotient[offset] = factor
        for index, value in enumerate(right):
            left[index + offset] = (left[index + offset] - factor * value) % prime
        _trim(left)
    return _trim(quotient), left


def _gcd(left: list[int], right: list[int], prime: int) -> list[int]:
    while right != [0]:
        left, right = right, _divide(left, right, prime)[1]
    inverse = pow(left[-1], -1, prime)
    return [value * inverse % prime for value in left]


def _power(base: list[int], exponent: int, modulus: list[int], prime: int) -> list[int]:
    result = [1]
    while exponent:
        if exponent & 1:
            result = _divide(_mod(_mul(result, base), prime), modulus, prime)[1]
        base = _divide(_mod(_mul(base, base), prime), modulus, prime)[1]
        exponent //= 2
    return result


def _irreducible_mod_prime(poly: list[int], prime: int) -> bool:
    """Rabin's degree-eight test, also excluding repeated modular factors."""
    modulus = _mod(poly, prime)
    derivative = _trim([index * modulus[index] for index in range(1, len(modulus))])
    if len(modulus) != 9 or modulus[-1] != 1 or _gcd(modulus, derivative, prime) != [1]:
        return False
    if _gcd(modulus, _add(_power([0, 1], prime**4, modulus, prime), [-1]), prime) != [1]:
        return False
    return _power([0, 1], prime**8, modulus, prime) == [0, 1]


def _sturm_roots(poly: list[int]) -> int:
    """Exact real-root count; used only for the at-most-ten tower survivors."""
    sequence = [poly[:], _trim([index * poly[index] for index in range(1, len(poly))])]
    while len(sequence[-1]) > 1:
        remainder = [Fraction(value) for value in sequence[-2]]
        divisor = [Fraction(value) for value in sequence[-1]]
        while len(remainder) >= len(divisor):
            factor = remainder[-1] / divisor[-1]
            offset = len(remainder) - len(divisor)
            for index, value in enumerate(divisor):
                remainder[index + offset] -= factor * value
            _trim(remainder)
        denominator = 1
        for value in remainder:
            denominator = denominator * value.denominator // gcd(denominator, value.denominator)
        sequence.append(_trim([-int(value * denominator) for value in remainder]))
    at_positive_infinity = [1 if item[-1] > 0 else -1 for item in sequence]
    at_negative_infinity = [sign * (-1) ** (len(item) - 1)
                            for sign, item in zip(at_positive_infinity, sequence)]
    changes = lambda signs: sum(left != right for left, right in zip(signs, signs[1:]))
    return changes(at_negative_infinity) - changes(at_positive_infinity)


def _controlled_tower(seed: int, serial: int) -> list[int] | None:
    """One bounded real biquadratic extension with controlled root signature."""
    a, b = PAIRS[_word(seed, 0, serial, 0) % len(PAIRS)]
    positives = TARGET_ROOTS[serial % len(TARGET_ROOTS)] // 2
    selected: tuple[tuple[int, int, int], int, int, int] | None = None
    for offset in range(24):
        triple = tuple(1 + _word(seed, 1, serial * 24 + offset, index) % 7 for index in range(3))
        constant = _controlled_constant(a, b, triple, positives)
        if constant is None:
            continue
        lam = 1 + _word(seed, 2, serial, offset) % 5
        mu = 1 + _word(seed, 3, serial, offset) % 5
        selected = triple, constant, lam, mu
        break
    if selected is None:
        return None
    triple, constant, lam, mu = selected
    # Exactly one characteristic-polynomial expansion per controlled slot.
    polynomial = _tower_characteristic([0, 1, lam, 0, mu, 0, 0, 0], (a, b, constant, *triple))
    if (len(polynomial) == 9 and polynomial[0]
            and any(_irreducible_mod_prime(polynomial, prime) for prime in PRIMES)
            and _sturm_roots(polynomial) == 2 * positives):
        return polynomial
    return None


def _canonical(poly: list[int]) -> tuple[int, ...]:
    """Identify the two primitive elements theta and -theta."""
    direct = tuple(poly)
    reflected = tuple((-1) ** degree * coefficient
                      for degree, coefficient in enumerate(poly))
    return min(direct, reflected)


def _base_product(left: tuple[int, int, int, int], right: tuple[int, int, int, int],
                  a: int, b: int) -> tuple[int, int, int, int]:
    """Multiply elements of Q(sqrt(a), sqrt(b)) in its natural basis."""
    result = [0] * 4
    for i, coefficient in enumerate(left):
        for j, other in enumerate(right):
            if not coefficient or not other:
                continue
            a_power = (i & 1) + (j & 1)
            b_power = ((i >> 1) & 1) + ((j >> 1) & 1)
            result[(a_power & 1) + 2 * (b_power & 1)] += (
                coefficient * other * (a if a_power == 2 else 1) *
                (b if b_power == 2 else 1)
            )
    return tuple(result)


def _conjugate(element: tuple[int, int, int, int], flip_a: bool,
               flip_b: bool) -> tuple[int, int, int, int]:
    """Apply base involutions; parity is Boolean, not integer bitwise XOR."""
    return tuple(value * (-1 if (flip_a and bool(index & 1)) ^
                 (flip_b and bool(index & 2)) else 1)
                 for index, value in enumerate(element))


def _relation_radicand(seed: int, lane: int, serial: int, height: int,
                       a: int, b: int) -> tuple[int, int, int, int] | None:
    """Return a radicand with a checked square-class relation certificate."""
    signed = lambda index: (_word(seed, lane + 20, serial, index) %
                            (2 * height + 1) - height)
    u = (signed(0) or 1, signed(1), signed(2), signed(3))
    v = (signed(4) or 1, signed(5), signed(6), signed(7))
    if lane == 0:
        radicand = (signed(8) or 1, signed(9), signed(10), signed(11))
        certificate = True
    elif lane == 1:
        mate = _conjugate(u, True, True)
        radicand = _base_product(u, mate, a, b)
        certificate = radicand == _base_product(u, mate, a, b)
    elif lane == 2:
        mate = _conjugate(u, True, False)
        radicand = _base_product(u, mate, a, b)
        certificate = radicand == _conjugate(radicand, True, False)
    else:
        first = _base_product(u, _conjugate(u, True, False), a, b)
        second = _base_product(v, _conjugate(v, False, True), a, b)
        radicand = _base_product(first, second, a, b)
        certificate = (first == _conjugate(first, True, False) and
                       second == _conjugate(second, False, True))
    if not certificate or not any(radicand[1:]):
        return None
    return radicand


def _relation_tower(seed: int, lane: int, serial: int, height: int) -> list[int] | None:
    """One bounded proposal from the generic or relation-engineered lanes."""
    a, b = PAIRS[_word(seed, lane + 30, serial, 0) % len(PAIRS)]
    radicand = _relation_radicand(seed, lane, serial, height, a, b)
    if radicand is None:
        return None
    theta = [0, 1 + _word(seed, lane + 35, serial, 1) % 4,
             1 + _word(seed, lane + 36, serial, 2) % 4, 0,
             1 + _word(seed, lane + 37, serial, 3) % 4, 0, 0, 0]
    return _tower_characteristic(theta, (a, b, *radicand))


def _compose(outer: list[int], inner: list[int]) -> list[int]:
    result = [0]
    for coefficient in reversed(outer):
        result = _add(_mul(result, inner), [coefficient])
    return result


def _supplement(seed: int, family: int, serial: int, height: int) -> list[int]:
    """Low-height non-tower constructions retained for portfolio breadth."""
    signed = lambda lane, index: (_word(seed, lane, serial, index) %
                                  (2 * height + 1) - height)
    if family == 4:  # a three-level quadratic tree
        quadratics = []
        for lane in range(3):
            linear = signed(50 + lane, 0)
            constant = signed(50 + lane, 1) or 1
            quadratics.append([constant, linear, 1])
        polynomial = _compose(quadratics[0], _compose(quadratics[1], quadratics[2]))
        polynomial[0] -= signed(54, 0) or 1
        return polynomial
    if family == 5:  # quadratic-relative shape f(x^2 + bx + c)
        quartic = [signed(55, index) for index in range(4)] + [1]
        quartic[0] = quartic[0] or 1
        return _compose(quartic, [signed(56, 0) or 1, signed(56, 1), 1])
    if family == 6:  # reciprocal octics
        values = [signed(57, index) for index in range(4)]
        return [1, values[0], values[1], values[2], values[3], values[2], values[1], values[0], 1]
    if family == 7:  # a sparse critical-orbit-style perturbation
        return [signed(58, 0) or 1, signed(58, 1), 0, signed(58, 2),
                signed(58, 3), 0, signed(58, 4), signed(58, 5), 1]
    return _completion(seed, serial + 100_000)


def _largest_remainder(total: int) -> list[int]:
    quotas = [total * weight // 100 for weight in PORTFOLIO_WEIGHTS]
    remainder = total - sum(quotas)
    order = sorted(range(len(quotas)), key=lambda index:
                   (-(total * PORTFOLIO_WEIGHTS[index] % 100), index))
    for index in order[:remainder]:
        quotas[index] += 1
    return quotas


def _portfolio_schedule(total: int) -> list[int]:
    """Smooth deterministic largest-remainder schedule for D's nine lanes."""
    quotas = _largest_remainder(total)
    used = [0] * len(quotas)
    schedule = []
    for position in range(total):
        lane = max((index for index in range(len(quotas)) if used[index] < quotas[index]),
                   key=lambda index: (quotas[index] * (position + 1) - used[index] * total,
                                      -index))
        used[lane] += 1
        schedule.append(lane)
    return schedule


def _acceptable(poly: list[int], seen: set[tuple[int, ...]], eisenstein: bool = False) -> bool:
    if len(poly) != 9 or poly[-1] != 1 or not poly[0] or _canonical(poly) in seen:
        return False
    return eisenstein or any(_irreducible_mod_prime(poly, prime) for prime in PRIMES)


def _completion(seed: int, position: int) -> list[int]:
    """Fast distinct Eisenstein octics retain the exact-budget guarantee."""
    # The adjusted sequence is injective in position and is never a multiple
    # of 101, so this is both collision-free within a call and Eisenstein.
    prime = 101
    constant = 2 * position + 1
    if constant % prime == 0:
        constant += 1
    coefficients = [prime * constant]
    for index in range(1, 8):
        coefficients.append(prime * (_word(seed, 10, position, index) % 31 - 15))
    return coefficients + [1]


def generate_candidates(seed: int, budget: int) -> list[list[int]]:
    """Return exactly ``budget`` unique monic integral octics.

    The first protected positions are the small archimedean probe.  The rest
    use a largest-remainder portfolio, with bounded attempts and a separate
    Eisenstein stream as the only completion mechanism.
    """
    if isinstance(budget, bool) or not isinstance(budget, int):
        raise TypeError("budget must be an integer")
    if budget < 0:
        raise ValueError("budget must be nonnegative")
    candidates: list[list[int]] = []
    seen: set[tuple[int, ...]] = set()
    controlled = min(10, budget)
    # At most six period positions are reserved.  This implementation keeps
    # the canary disabled until it has an independently validated exact pool;
    # those positions therefore spill immediately rather than pretending that
    # generic cyclotomic-looking polynomials are Gaussian periods.
    period_positions = min(6, budget // 200, budget - controlled)

    # One expansion per requested controlled signature; failure never causes a
    # broader search in this protected lane.
    for serial in range(controlled):
        polynomial = _controlled_tower(seed, serial)
        if polynomial is not None and _acceptable(polynomial, seen):
            candidates.append(polynomial)
            seen.add(_canonical(polynomial))

    remaining = budget - controlled - period_positions
    serials = [0] * len(PORTFOLIO_WEIGHTS)
    for position, family in enumerate(_portfolio_schedule(remaining)):
        chosen: list[int] | None = None
        # A fixed two-proposal shell is enough to avoid routine collisions,
        # while retaining predictable cost for a two-thousand candidate call.
        for attempt in range(2):
            serial = serials[family]
            serials[family] += 1
            height = SHELLS[(serial + attempt + _word(seed, family + 60, position, 0)) % len(SHELLS)]
            if family < 4:
                proposal = _relation_tower(seed, family, serial, height)
            else:
                proposal = _supplement(seed, family, serial, height)
            if proposal is not None and _acceptable(proposal, seen, family == 8):
                chosen = proposal
                break
        if chosen is None:
            chosen = _completion(seed, position)
            # Completion's constant term is injective in this schedule; a
            # collision can only be with an earlier non-completion proposal.
            if _canonical(chosen) in seen:
                chosen = _completion(seed, position + budget + 1)
        candidates.append(chosen)
        seen.add(_canonical(chosen))

    # Failed controlled slots and the gated canary spill only here.  The
    # position is deterministic and completion has an injective constant term.
    position = remaining
    while len(candidates) < budget:
        polynomial = _completion(seed, position)
        position += 1
        # Earlier completion values have smaller positions.  A screened
        # proposal could only collide by matching every 101-divisible
        # coefficient, so three explicitly bounded alternatives are ample.
        for offset in range(3):
            alternative = polynomial if offset == 0 else _completion(
                seed, position + offset * (budget + 1))
            key = _canonical(alternative)
            if key not in seen:
                candidates.append(alternative)
                seen.add(key)
                break
        else:
            # This branch is unreachable for ordinary proposals; keep the
            # exact-budget contract without introducing a rejection loop.
            raise RuntimeError("bounded Eisenstein completion collision")
    return candidates
