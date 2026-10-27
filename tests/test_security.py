import os
import sys
import time

import pytest
from conftest import SECRET

from safe_git_mcp.backend import Backend, Budget, capture
from safe_git_mcp.config import Policy
from safe_git_mcp.errors import SafeError


def test_alternates_rejected(repo):
    (repo.root / ".git/objects/info/alternates").write_text("/nonexistent\n")
    with pytest.raises(SafeError):
        Backend(Policy(repository_root=repo.root))


def test_replace_objects_rejected(repo):
    repo.git("replace", repo.git("rev-parse", "HEAD"), repo.git("rev-parse", "HEAD^"))
    with pytest.raises(SafeError):
        Backend(Policy(repository_root=repo.root))


def test_config_include_rejected(repo):
    repo.git("config", "include.path", "/nonexistent")
    with pytest.raises(SafeError):
        Backend(Policy(repository_root=repo.root))


def test_binding_change_rejected(repo):
    b = Backend(Policy(repository_root=repo.root))
    repo.git("config", "core.bare", "true")
    with pytest.raises(SafeError):
        b.resolve("HEAD")


def test_inherited_git_environment_cleared(repo, monkeypatch):
    expected = repo.git("rev-parse", "HEAD")
    monkeypatch.setenv("GIT_DIR", "/does-not-exist")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "alias.log")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "!echo " + SECRET)
    assert Backend(Policy(repository_root=repo.root)).resolve("HEAD") == expected


def test_capture_timeout_and_output_cap(tmp_path):
    for script, cap, seconds, code in [
        ("import time; time.sleep(5)", 1024, 0.1, "TIMEOUT"),
        ('import sys; sys.stdout.write("x"*100000)', 32, 2, "OUTPUT_LIMIT"),
        ('import sys; sys.stderr.write("' + SECRET + '"); sys.exit(1)', 1024, 2, "INTERNAL_ERROR"),
    ]:
        start = time.monotonic()
        with pytest.raises(SafeError) as e:
            capture(
                [sys.executable, "-c", script],
                tmp_path,
                {"PATH": os.defpath},
                Budget(seconds, cap, 5),
            )
        assert e.value.code == code
        assert SECRET not in str(e.value)
        assert time.monotonic() - start < 3


def test_request_subprocess_budget(repo):
    b = Backend(Policy(repository_root=repo.root))
    with b.operation():
        b.budget.calls = 0
        with pytest.raises(SafeError) as e:
            b.resolve("HEAD")
        assert e.value.code == "OUTPUT_LIMIT"


def test_corrupted_git_output_is_not_returned(repo, monkeypatch):
    from safe_git_mcp.history import History

    h = History(Policy(repository_root=repo.root))
    real_run = h.backend._run

    def corrupt(args, cap=None):
        if args[0] == "diff-tree":
            return b"corrupt " + SECRET.encode()
        return real_run(args, cap)

    monkeypatch.setattr(h.backend, "_run", corrupt)
    with pytest.raises(SafeError) as e:
        h.git_show_commit("HEAD")
    assert SECRET not in str(e.value)


def test_patch_parser_rejects_wrong_file_and_unframed_data():
    from safe_git_mcp.patches import validate_patch

    for raw in [
        b"diff --git a/env/secret b/env/secret\n" + SECRET.encode() + b"\n",
        b"diff --git a/safe b/safe\n" + SECRET.encode() + b"\n",
        b"diff --git a/safe b/safe\n@@ -1 +1 @@\n+extra\n",
    ]:
        with pytest.raises(SafeError):
            validate_patch(raw, "safe")


def test_timeout_kills_descendant_process_group(tmp_path):
    import subprocess

    marker = tmp_path / "should-not-exist"
    child = f"import time,pathlib; time.sleep(0.5); pathlib.Path({str(marker)!r}).touch()"
    parent = (
        "import subprocess,sys,time; "
        f'subprocess.Popen([sys.executable,"-c",{child!r}]); time.sleep(10)'
    )
    with pytest.raises(SafeError) as e:
        capture(
            [sys.executable, "-c", parent], tmp_path, {"PATH": os.defpath}, Budget(0.15, 4096, 1)
        )
    assert e.value.code == "TIMEOUT"
    # A separate waiter makes the delayed side effect observable without orphaning a fixture child.
    subprocess.run([sys.executable, "-c", "import time; time.sleep(0.7)"], check=True)
    assert not marker.exists()


def test_alternate_added_after_start_is_rejected(repo):
    b = Backend(Policy(repository_root=repo.root))
    (repo.root / ".git/objects/info/alternates").write_text("/nonexistent\n")
    with pytest.raises(SafeError):
        b.resolve("HEAD")


def test_unreadable_policy_fails_closed(tmp_path):
    # A directory is deterministically unreadable as a policy file, including under privileged CI.
    with pytest.raises(SafeError):
        Policy.load(tmp_path)


def test_promisor_missing_blob_never_executes_remote_helper(repo, tmp_path):
    from safe_git_mcp.history import History

    marker = tmp_path / "remote-helper-ran"
    helper = tmp_path / "upload-pack"
    helper.write_text(f'#!/bin/sh\ntouch "{marker}"\nexit 1\n')
    helper.chmod(0o755)
    blob = repo.git("rev-parse", "HEAD:apps/core/src/routing.erl")
    repo.git("config", "remote.origin.url", str(repo.root))
    repo.git("config", "remote.origin.promisor", "true")
    repo.git("config", "remote.origin.uploadpack", str(helper))
    (repo.root / ".git/objects" / blob[:2] / blob[2:]).unlink()
    with pytest.raises(SafeError):
        History(Policy(repository_root=repo.root)).git_show_commit("HEAD")
    assert not marker.exists()


def test_capture_enforces_cpu_resource_limit(tmp_path):
    import json

    raw = capture(
        [
            sys.executable,
            "-c",
            "import resource,json; print(json.dumps(resource.getrlimit(resource.RLIMIT_CPU)))",
        ],
        tmp_path,
        {"PATH": os.defpath},
        Budget(2, 4096, 1),
    )
    soft, hard = json.loads(raw)
    assert 0 < soft <= 2
    assert soft <= hard <= 3
