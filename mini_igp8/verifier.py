"""Exact SageMath verification for degree-8 candidates.

Search verification computes only facts needed by the public catalogue. Hidden
screen/benchmark/race evaluations can skip the polynomial discriminant to stay
on the fast path.
"""

from __future__ import annotations

import operator
import signal
from contextlib import contextmanager
from functools import lru_cache


DEGREE = 8


class SageUnavailableError(RuntimeError):
    """SageMath is unavailable in the active Python environment."""


class VerificationTimeoutError(TimeoutError):
    """One exact Sage computation exceeded its operational time allowance."""


def validate_coefficients(candidate: object) -> list[int]:
    """Validate the solver output format; coefficient magnitude is unrestricted."""

    if not isinstance(candidate, (list, tuple)):
        raise ValueError("candidate_not_list_or_tuple")
    if len(candidate) != DEGREE + 1:
        raise ValueError(f"candidate_wrong_length:expected=9:actual={len(candidate)}")

    coefficients: list[int] = []
    for value in candidate:
        if isinstance(value, bool):
            raise ValueError("candidate_boolean_coefficient")
        try:
            coefficients.append(int(operator.index(value)))
        except TypeError as exc:
            raise ValueError("candidate_noninteger_coefficient") from exc

    if coefficients[-1] != 1:
        raise ValueError("candidate_not_monic")
    if coefficients[0] == 0:
        raise ValueError("candidate_zero_constant")
    return coefficients


@lru_cache(maxsize=1)
def _sage_context():
    try:
        from sage.all import NumberField, PolynomialRing, QQ
    except ModuleNotFoundError as exc:
        if exc.name == "sage" or (exc.name or "").startswith("sage."):
            raise SageUnavailableError(
                "SageMath is unavailable. Activate the mini-igp8 conda "
                "environment and use its python interpreter."
            ) from exc
        raise
    return NumberField, PolynomialRing(QQ, "x")


def ensure_sage_available() -> None:
    _sage_context()


@contextmanager
def _time_limit(seconds: int | float | None):
    if not seconds or not hasattr(signal, "setitimer"):
        yield
        return

    def expired(_signum, _frame):
        raise VerificationTimeoutError("verification_timeout")

    previous = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, float(seconds))
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def verify(
    candidate: object,
    *,
    timeout_seconds: int | float | None = None,
    include_polynomial_discriminant: bool = True,
) -> dict:
    """Verify one candidate exactly.

    ``include_polynomial_discriminant=False`` is used for hidden tournament
    samples, where the discriminant is irrelevant to the primary selection
    signal. Public search keeps it enabled for the secondary discriminant
    objective.
    """

    try:
        coefficients = validate_coefficients(candidate)
    except ValueError as exc:
        return {"status": "invalid_candidate", "reason_code": str(exc)}

    try:
        with _time_limit(timeout_seconds):
            return _verify_valid(
                coefficients,
                include_polynomial_discriminant=include_polynomial_discriminant,
            )
    except VerificationTimeoutError:
        return {
            "status": "verification_timeout",
            "reason_code": "verification_time_limit_exceeded",
            "coefficients": coefficients,
        }


def _verify_valid(
    coefficients: list[int],
    *,
    include_polynomial_discriminant: bool,
) -> dict:
    _NumberField, ring = _sage_context()
    polynomial = ring(coefficients)
    common = {"coefficients": coefficients}

    try:
        if not bool(polynomial.is_irreducible()):
            return {"status": "reducible", **common}
    except VerificationTimeoutError:
        raise
    except Exception as exc:
        return {
            "status": "irreducibility_error",
            "reason_code": type(exc).__name__,
            **common,
        }

    try:
        real_roots = int(polynomial.number_of_real_roots())
    except VerificationTimeoutError:
        raise
    except Exception as exc:
        return {
            "status": "root_count_error",
            "reason_code": type(exc).__name__,
            **common,
        }

    try:
        group = polynomial.galois_group(pari_group=True, algorithm="pari")
        transitive_number = int(group.transitive_number())
    except VerificationTimeoutError:
        raise
    except Exception as exc:
        return {
            "status": "galois_group_error",
            "reason_code": type(exc).__name__,
            "real_roots": real_roots,
            **common,
        }

    result = {
        "status": "verified",
        **common,
        "galois_group": f"8T{transitive_number}",
        "real_roots": real_roots,
    }

    if include_polynomial_discriminant:
        try:
            result["polynomial_discriminant"] = abs(int(polynomial.discriminant()))
        except VerificationTimeoutError:
            raise
        except Exception as exc:
            return {
                "status": "polynomial_discriminant_error",
                "reason_code": type(exc).__name__,
                **result,
            }

    return result


def field_discriminant(
    candidate: object,
    *,
    timeout_seconds: int | float | None = None,
) -> int:
    """Compute the absolute number-field discriminant for one verified candidate."""

    coefficients = validate_coefficients(candidate)
    NumberField, ring = _sage_context()
    with _time_limit(timeout_seconds):
        polynomial = ring(coefficients)
        return abs(int(NumberField(polynomial, "a").discriminant()))
