"""Run untrusted Python in a throwaway Docker container (defensive containment only).

Isolation applied to every run:
  --network none            no network at all
  --read-only + tmpfs       root fs is read-only; only a small tmpfs /tmp is writable
  --user 65534:65534        non-root ("nobody")
  --cpus / --memory / --pids-limit   resource caps
  --cap-drop ALL, no-new-privileges  no extra privileges
  wall-clock timeout        container is force-removed when it expires
  NO host mounts            the code is piped through stdin, nothing is bind-mounted

When something is stopped, `SandboxResult.blocked` holds a human-readable reason so the
agent loop can emit a "blocked" event (the demo's "containment moment").
"""

from __future__ import annotations

import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from typing import Protocol

from app.config import Settings

MAX_OUTPUT = 4000

# Substrings in stderr that tell us a policy (not a bug in the code) stopped it.
_NETWORK_HINTS = re.compile(
    r"Network is unreachable|Temporary failure in name resolution|Name or service not known"
    r"|nodename nor servname|Errno 101|Errno -3|Errno -2\]|No route to host|Connection refused",
    re.I,
)
_FS_HINTS = re.compile(r"Read-only file system|Errno 30|Permission denied", re.I)


@dataclass
class SandboxResult:
    ok: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    blocked: str | None = None  # human-readable reason, None if nothing was blocked
    blocked_kind: str | None = None  # network | timeout | oom | filesystem
    runner: str = "docker"  # docker | mock


class SandboxRunner(Protocol):
    name: str

    def run(self, code: str) -> SandboxResult: ...


def _clip(text: str) -> str:
    return text if len(text) <= MAX_OUTPUT else text[:MAX_OUTPUT] + "\n...[truncated]"


class DockerSandbox:
    name = "docker"

    def __init__(self, settings: Settings) -> None:
        self.s = settings

    def build_command(self, container_name: str) -> list[str]:
        s = self.s
        return [
            "docker", "run", "-i",
            "--name", container_name,
            "--pull", "never",  # pre-pull the image on the VM (see deploy/DEPLOY.md)
            "--network", "none",
            "--read-only",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m",
            "--workdir", "/tmp",
            "--user", "65534:65534",
            "--cpus", s.sandbox_cpus,
            "--memory", s.sandbox_memory,
            "--memory-swap", s.sandbox_memory,  # same as memory => no swap
            "--pids-limit", str(s.sandbox_pids),
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            s.sandbox_image,
            "python", "-I", "-c",
            "import sys; exec(compile(sys.stdin.read(), '<sandbox>', 'exec'))",
        ]  # fmt: skip

    def run(self, code: str) -> SandboxResult:
        name = f"sandbox-{uuid.uuid4().hex[:12]}"
        try:
            try:
                proc = subprocess.run(
                    self.build_command(name),
                    input=code,
                    capture_output=True,
                    text=True,
                    timeout=self.s.sandbox_timeout,
                )
            except subprocess.TimeoutExpired:
                return SandboxResult(
                    ok=False,
                    blocked=(
                        f"Killed: code ran longer than the {self.s.sandbox_timeout:g}s "
                        "wall-clock limit."
                    ),
                    blocked_kind="timeout",
                )
            return self._interpret(proc, name)
        finally:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=20)

    def _interpret(self, proc: subprocess.CompletedProcess[str], name: str) -> SandboxResult:
        out, err = _clip(proc.stdout or ""), _clip(proc.stderr or "")
        base = {"stdout": out, "stderr": err, "exit_code": proc.returncode}
        if proc.returncode == 0:
            return SandboxResult(ok=True, **base)
        if proc.returncode == 137 and self._was_oom(name):
            return SandboxResult(
                ok=False,
                blocked=f"Killed: code exceeded the {self.s.sandbox_memory} memory limit.",
                blocked_kind="oom",
                **base,
            )
        if _NETWORK_HINTS.search(err):
            return SandboxResult(
                ok=False,
                blocked="Blocked: code tried to use the network, but the sandbox has none.",
                blocked_kind="network",
                **base,
            )
        if _FS_HINTS.search(err):
            return SandboxResult(
                ok=False,
                blocked="Blocked: code tried to write outside the small temp dir (read-only fs).",
                blocked_kind="filesystem",
                **base,
            )
        return SandboxResult(ok=False, **base)  # plain bug in the code, not a containment event

    @staticmethod
    def _was_oom(name: str) -> bool:
        p = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.OOMKilled}}", name],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return p.stdout.strip() == "true"


class MockSandbox:
    """Pretends to run code. Used when Docker is unavailable or SANDBOX_ENABLED=false.

    It never executes anything; it only looks at the text of the code to decide which
    containment story to tell.
    """

    name = "mock"

    def run(self, code: str) -> SandboxResult:
        c = code.lower()
        if any(k in c for k in ("urllib", "requests", "socket", "http")):
            return SandboxResult(
                ok=False,
                stderr="URLError: [Errno 101] Network is unreachable",
                blocked="Blocked (mock): code tried to use the network, but the sandbox has none.",
                blocked_kind="network",
                runner="mock",
            )
        if "while true" in c:
            return SandboxResult(
                ok=False,
                blocked="Killed (mock): code ran longer than the wall-clock limit.",
                blocked_kind="timeout",
                runner="mock",
            )
        return SandboxResult(
            ok=True, stdout="(mock sandbox - code was NOT executed)\n", exit_code=0, runner="mock"
        )


def docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=5).returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


def get_runner(settings: Settings) -> SandboxRunner:
    if settings.sandbox_enabled and docker_available():
        return DockerSandbox(settings)
    return MockSandbox()
