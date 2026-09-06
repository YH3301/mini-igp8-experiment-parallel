import unittest
from unittest.mock import patch

from mini_igp8.verifier import (
    VerificationTimeoutError,
    validate_coefficients,
    verify,
)


class VerifierTests(unittest.TestCase):
    def test_no_coefficient_magnitude_limit(self):
        candidate = [10**100, -10**80, 0, 0, 0, 0, 0, 0, 1]
        self.assertEqual(validate_coefficients(candidate), candidate)

    def test_format_failures_are_specific(self):
        cases = [
            ("bad", "candidate_not_list_or_tuple"),
            ([1] * 8, "candidate_wrong_length"),
            ([True] + [0] * 7 + [1], "candidate_boolean_coefficient"),
            ([1.5] + [0] * 7 + [1], "candidate_noninteger_coefficient"),
            ([1] + [0] * 7 + [2], "candidate_not_monic"),
            ([0] * 8 + [1], "candidate_zero_constant"),
        ]
        for candidate, code in cases:
            with self.subTest(code=code), self.assertRaisesRegex(ValueError, code):
                validate_coefficients(candidate)

    def test_timeout_has_its_own_status(self):
        with patch("mini_igp8.verifier._verify_valid", side_effect=VerificationTimeoutError()):
            result = verify([1] + [0] * 7 + [1], timeout_seconds=1)
        self.assertEqual(result["status"], "verification_timeout")


if __name__ == "__main__":
    unittest.main()
