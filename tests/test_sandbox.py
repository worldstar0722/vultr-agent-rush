import subprocess
from types import SimpleNamespace

from app.config import Settings
from app.sandbox import DockerSandbox, MockSandbox, get_runner
from tests.conftest import read_events


def fake_docker(monkeypatch, *, returncode=0, stdout="", stderr="", timeout=False, oom=False):
    """Replace subprocess.run so no real Docker is needed. Returns the list of commands."""
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if cmd[1] == "run":
            if timeout:
                raise subprocess.TimeoutExpired(cmd, kw["timeout"])
            return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)
        if cmd[1] == "inspect":
            return SimpleNamespace(returncode=0, stdout="true\n" if oom else "false\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")  # docker rm

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


def test_docker_command_has_isolation_flags(monkeypatch):
    calls = fake_docker(monkeypatch, stdout="hi\n")
    res = DockerSandbox(Settings()).run("print('hi')")
    assert res.ok and res.stdout == "hi\n"
    cmd = " ".join(calls[0])
    for flag in (
        "--network none",
        "--read-only",
        "--tmpfs /tmp",
        "--user 65534:65534",
        "--cpus",
        "--memory",
        "--pids-limit",
        "--cap-drop ALL",
    ):
        assert flag in cmd
    assert " -v " not in cmd and "--volume" not in cmd  # no host mounts
    assert calls[-1][:3] == ["docker", "rm", "-f"]  # always cleaned up


def test_network_attempt_is_blocked(monkeypatch):
    fake_docker(
        monkeypatch,
        returncode=1,
        stderr="urllib.error.URLError: <urlopen error [Errno 101] Network is unreachable>",
    )
    res = DockerSandbox(Settings()).run("...")
    assert not res.ok and res.blocked_kind == "network" and "network" in res.blocked


def test_timeout_is_blocked(monkeypatch):
    calls = fake_docker(monkeypatch, timeout=True)
    res = DockerSandbox(Settings(sandbox_timeout=1)).run("while True: pass")
    assert res.blocked_kind == "timeout" and "wall-clock" in res.blocked
    assert calls[-1][:3] == ["docker", "rm", "-f"]


def test_oom_is_blocked(monkeypatch):
    fake_docker(monkeypatch, returncode=137, oom=True)
    assert DockerSandbox(Settings()).run("x").blocked_kind == "oom"


def test_plain_bug_is_not_a_containment_event(monkeypatch):
    fake_docker(monkeypatch, returncode=1, stderr="NameError: name 'x' is not defined")
    res = DockerSandbox(Settings()).run("x")
    assert not res.ok and res.blocked is None


def test_mock_runner_and_fallback_without_docker(monkeypatch):
    assert MockSandbox().run("import urllib.request").blocked_kind == "network"
    assert MockSandbox().run("print(1)").ok
    monkeypatch.setattr("app.sandbox.runner.docker_available", lambda: False)
    assert get_runner(Settings(sandbox_enabled=True)).name == "mock"


def test_blocked_event_reaches_the_timeline(client):
    """End to end (mock runner): a network attempt shows up as a 'blocked' event."""
    run_id = client.post("/api/runs", json={"task": "download a page from the internet"}).json()[
        "id"
    ]
    events = read_events(client, run_id)
    blocked = [e for e in events if e["type"] == "blocked"]
    assert blocked and blocked[0]["data"]["kind"] == "network"
    assert events[-1]["type"] == "done"
