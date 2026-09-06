"""A narrow, correctly classified Codex CLI boundary."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            self.input_tokens + other.input_tokens,
            self.cached_input_tokens + other.cached_input_tokens,
            self.output_tokens + other.output_tokens,
            self.reasoning_tokens + other.reasoning_tokens,
        )


@dataclass(frozen=True)
class CodexResponse:
    text: str
    data: dict | None
    usage: TokenUsage


class CodexFailure(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}:{detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class CommandRunner:
    def run(self, argv: list[str], *, cwd: Path, timeout: float | None) -> CommandResult:
        completed = subprocess.run(
            argv, cwd=cwd, capture_output=True, text=True, check=False, timeout=timeout,
        )
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _usage(events: str) -> TokenUsage:
    total = TokenUsage()
    for line in events.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "turn.completed" or not isinstance(event.get("usage"), dict):
            continue
        values = event["usage"]
        total += TokenUsage(
            input_tokens=int(values.get("input_tokens", 0) or 0),
            cached_input_tokens=int(values.get("cached_input_tokens", 0) or 0),
            output_tokens=int(values.get("output_tokens", 0) or 0),
            reasoning_tokens=int(values.get("reasoning_output_tokens", 0) or 0),
        )
    return total


def _failure_code(stderr: str) -> str:
    """Classify only a failed process's diagnostic stream."""

    text = stderr.lower()
    patterns = (
        ("ai_authentication_failed", r"authentication (?:is )?required|not logged in|please sign in|\b401\b.*unauthor"),
        ("ai_rate_limit_reached", r"rate limit|too many requests|\b429\b"),
        ("ai_model_unavailable", r"model .*not supported|model .*unavailable|unknown model"),
        ("ai_network_failed", r"connection|network|dns|tls|socket|transport"),
    )
    for code, pattern in patterns:
        if re.search(pattern, text):
            return code
    return "ai_process_failed"


def codex_version(executable: str = "codex") -> tuple[int, int, int] | None:
    path = shutil.which(executable)
    if not path:
        return None
    completed = subprocess.run([path, "--version"], capture_output=True, text=True, check=False)
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", completed.stdout + completed.stderr)
    return tuple(map(int, match.groups())) if completed.returncode == 0 and match else None


def ensure_codex(minimum: tuple[int, int, int] = (0, 144, 0)) -> None:
    version = codex_version()
    if version is None:
        raise CodexFailure("ai_cli_unavailable", "Codex CLI is missing or unreadable")
    if version < minimum:
        raise CodexFailure(
            "ai_cli_too_old",
            f"required={'.'.join(map(str, minimum))}:found={'.'.join(map(str, version))}",
        )


class CodexClient:
    def __init__(self, *, runner: CommandRunner | None = None, executable: str = "codex"):
        self.runner = runner or CommandRunner()
        self.executable = executable

    def call(
        self,
        *,
        prompt: str,
        cwd: Path,
        model: str,
        reasoning: str,
        sandbox: str,
        timeout: float | None,
        schema: dict | None = None,
    ) -> CodexResponse:
        with tempfile.TemporaryDirectory(prefix="mini-igp8-codex-") as temporary:
            temporary_path = Path(temporary)
            final_path = temporary_path / "final.txt"
            argv = [
                self.executable, "exec", "--json", "--ignore-user-config", "--ignore-rules",
                "-c", f'model_reasoning_effort="{reasoning}"',
                "--sandbox", sandbox, "--model", model,
            ]
            if schema is not None:
                schema_path = temporary_path / "schema.json"
                schema_path.write_text(json.dumps(schema), encoding="utf-8")
                argv.extend(["--output-schema", str(schema_path)])
            argv.extend(["-o", str(final_path), prompt])
            try:
                result = self.runner.run(argv, cwd=cwd, timeout=timeout)
            except FileNotFoundError as exc:
                raise CodexFailure("ai_cli_unavailable", "Codex CLI not found") from exc
            except subprocess.TimeoutExpired as exc:
                raise CodexFailure("ai_call_timeout", "Codex call exceeded the session time limit") from exc

            # Success is decided before inspecting any generated text. This prevents
            # source code such as ``for sign in signs`` from becoming a fake auth error.
            if result.returncode != 0:
                detail = result.stderr.strip() or "Codex exited without a diagnostic"
                raise CodexFailure(_failure_code(result.stderr), detail[:500])
            if not final_path.exists():
                raise CodexFailure("ai_missing_final_output", "successful process created no final output")

            text = final_path.read_text(encoding="utf-8").strip()
            data = None
            if schema is not None:
                try:
                    data = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise CodexFailure("ai_invalid_json", str(exc)) from exc
                if not isinstance(data, dict):
                    raise CodexFailure("ai_invalid_json_type", "expected a JSON object")
            return CodexResponse(text=text, data=data, usage=_usage(result.stdout))
