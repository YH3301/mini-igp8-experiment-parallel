import json
import tempfile
import unittest
from pathlib import Path

from mini_igp8.codex import CodexClient, CodexFailure, CommandResult


class FakeRunner:
    def __init__(self, result, final="{}"):
        self.result = result
        self.final = final
        self.argv = None

    def run(self, argv, *, cwd, timeout):
        self.argv = argv
        if self.result.returncode == 0:
            Path(argv[argv.index("-o") + 1]).write_text(self.final)
        return self.result


class CodexTests(unittest.TestCase):
    def test_successful_source_text_cannot_become_fake_auth_failure(self):
        events = json.dumps({
            "type": "item.completed",
            "item": {"text": "for sign in signs: pass"},
        }) + "\n" + json.dumps({
            "type": "turn.completed",
            "usage": {"input_tokens": 12, "cached_input_tokens": 4,
                      "output_tokens": 3, "reasoning_output_tokens": 2},
        })
        client = CodexClient(runner=FakeRunner(CommandResult(0, events, "")))
        with tempfile.TemporaryDirectory() as temporary:
            response = client.call(
                prompt="p", cwd=Path(temporary), model="m", reasoning="high",
                sandbox="read-only", timeout=5,
            )
        self.assertEqual(response.usage.input_tokens, 12)

    def test_authentication_requires_failed_process_diagnostic(self):
        client = CodexClient(runner=FakeRunner(CommandResult(1, "", "Authentication is required")))
        with tempfile.TemporaryDirectory() as temporary, self.assertRaises(CodexFailure) as caught:
            client.call(
                prompt="p", cwd=Path(temporary), model="m", reasoning="high",
                sandbox="read-only", timeout=5,
            )
        self.assertEqual(caught.exception.code, "ai_authentication_failed")

    def test_successful_final_json_is_parsed(self):
        runner = FakeRunner(CommandResult(0, "", ""), '{"value": 1}')
        client = CodexClient(runner=runner)
        with tempfile.TemporaryDirectory() as temporary:
            response = client.call(
                prompt="p", cwd=Path(temporary), model="m", reasoning="low",
                sandbox="read-only", timeout=5, schema={"type": "object"},
            )
        self.assertEqual(response.data, {"value": 1})
        self.assertIn("--ignore-user-config", runner.argv)
        self.assertIn("--ignore-rules", runner.argv)
        self.assertNotIn("danger-full-access", runner.argv)


if __name__ == "__main__":
    unittest.main()
