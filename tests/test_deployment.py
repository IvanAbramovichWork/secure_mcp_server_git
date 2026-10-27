import json
import os
import subprocess
import sys

import pytest
from conftest import SECRET

from safe_git_mcp.config import Policy


def cli(*args, env=None):
    return subprocess.run(
        [sys.executable, "-m", "safe_git_mcp", *map(str, args)],
        capture_output=True,
        text=True,
        input="",
        timeout=20,
        env=env,
    )


def policy_file(repo, tmp_path):
    policy = tmp_path / "policy.toml"
    policy.write_text(f'repository_root = "{repo.root}"\n')
    return policy


def test_doctor_checks_real_stdio(repo, tmp_path):
    r = cli("doctor", "--policy", policy_file(repo, tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(r.stdout)["code"] == "READY"
    assert SECRET not in r.stdout + r.stderr


def test_doctor_identifies_bad_policy(tmp_path):
    p = tmp_path / "bad.toml"
    p.write_text('repository_root="~/not-expanded"\n')
    r = cli("doctor", "--policy", p)
    assert r.returncode == 1
    assert json.loads(r.stdout)["code"] == "POLICY_INVALID"
    assert "absolute" in r.stdout


def test_worktree_diagnostic_does_not_follow_pointer(repo, tmp_path):
    # A fake pointer proves diagnostics need not read the destination or original history.
    worktree = tmp_path / "linked"
    worktree.mkdir()
    (worktree / ".git").write_text("gitdir: /unreadable/" + SECRET)
    p = tmp_path / "linked.toml"
    p.write_text(f'repository_root="{worktree}"\n')
    r = cli("doctor", "--policy", p)
    assert r.returncode == 1
    assert json.loads(r.stdout)["code"] == "LINKED_WORKTREE_UNSUPPORTED"
    assert SECRET not in r.stdout + r.stderr


def test_setup_expands_tilde_and_generates_separate_policy(repo, tmp_path):
    env = {**os.environ, "HOME": str(tmp_path)}
    r = cli("setup", "--repo", "~/synthetic", "--name", "project-a", env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    p = tmp_path / ".config/safe-git-mcp/project-a.toml"
    policy = Policy.load(p)
    assert policy.repository_root == repo.root
    assert not policy.allows("env/production.config")
    assert not policy.allows("nested/key.pem")
    assert not policy.allows(".env")
    assert policy.quarantine_literals
    assert p.stat().st_mode & 0o777 == 0o600
    data = json.loads(r.stdout)
    assert data["registration_argv"][:7] == [
        "eltex-claude",
        "mcp",
        "add",
        "--transport",
        "stdio",
        "--scope",
        "user",
    ]
    assert data["registration_argv"][7] == "safe-git-project-a"
    assert data["registration_argv"][-1] == str(p)
    assert "--policy" in data["registration_command"]


def test_setup_preserves_existing_reviewed_policy(repo, tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    p = config / "project.toml"
    text = f'repository_root="{repo.root}"\nmax_commits=7\n'
    p.write_text(text)
    r = cli("setup", "--repo", repo.root, "--name", "project", "--config-dir", config)
    assert r.returncode == 0, r.stdout + r.stderr
    assert p.read_text() == text


def test_setup_refuses_existing_other_binding(repo, tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    p = config / "project.toml"
    text = 'repository_root="/different/approved/project"\n'
    p.write_text(text)
    r = cli("setup", "--repo", repo.root, "--name", "project", "--config-dir", config)
    assert r.returncode == 1
    assert json.loads(r.stdout)["code"] == "POLICY_CONFLICT"
    assert p.read_text() == text


@pytest.mark.parametrize("name", ["../escape", "-p", "two words", "a;id"])
def test_setup_invalid_names_never_create_files(repo, tmp_path, name):
    config = tmp_path / "config"
    r = cli("setup", "--repo", repo.root, "--name=" + name, "--config-dir", config)
    assert r.returncode != 0
    assert not config.exists()


def test_setup_rejected_repository_does_not_write_policy(repo, tmp_path):
    repo.git("config", "include.path", "/nonexistent")
    config = tmp_path / "config"
    r = cli("setup", "--repo", repo.root, "--name", "test", "--config-dir", config)
    assert r.returncode == 1
    assert json.loads(r.stdout)["code"] == "REPOSITORY_REJECTED"
    assert not config.exists()


def test_registration_uses_argv_and_does_not_echo_client_output(repo, tmp_path):
    record = tmp_path / "arguments.json"
    client = tmp_path / "client with spaces"
    client.write_text(
        f"#!{sys.executable}\nimport sys,json\n"
        f'json.dump(sys.argv[1:],open({str(record)!r},"w"))\nprint({SECRET!r})\n'
    )
    client.chmod(0o755)
    config = tmp_path / "policy with spaces"
    r = cli(
        "setup",
        "--repo",
        repo.root,
        "--name",
        "demo",
        "--config-dir",
        config,
        "--client",
        client,
        "--register",
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(record.read_text())[-1] == str(config / "demo.toml")
    assert json.loads(r.stdout)["registered"] is True
    assert SECRET not in r.stdout + r.stderr


def test_registration_failure_preserves_generated_policy(repo, tmp_path):
    config = tmp_path / "config"
    r = cli(
        "setup",
        "--repo",
        repo.root,
        "--name",
        "demo",
        "--config-dir",
        config,
        "--client",
        "/nonexistent/client",
        "--register",
    )
    assert r.returncode == 1
    assert json.loads(r.stdout)["code"] == "CLIENT_REGISTRATION_FAILED"
    assert (config / "demo.toml").exists()


def test_missing_prlimit_is_actionable(repo, monkeypatch):
    import safe_git_mcp.deployment as deployment

    original_access = deployment.os.access
    monkeypatch.setattr(
        deployment.os,
        "access",
        lambda path, mode: (
            False if str(path) == "/usr/bin/prlimit" else original_access(path, mode)
        ),
    )
    with pytest.raises(deployment.DeploymentError) as error:
        deployment.check_repository(Policy(repository_root=repo.root))
    assert error.value.code == "PRLIMIT_MISSING"
    assert "util-linux" in str(error.value)


def test_missing_git_is_actionable(repo, monkeypatch):
    import safe_git_mcp.deployment as deployment

    monkeypatch.setattr(deployment.shutil, "which", lambda *a, **kw: None)
    with pytest.raises(deployment.DeploymentError) as error:
        deployment.check_repository(Policy(repository_root=repo.root))
    assert error.value.code == "GIT_MISSING"


def test_setup_worktree_does_not_create_policy(tmp_path):
    root = tmp_path / "linked"
    root.mkdir()
    (root / ".git").write_text("gitdir: /never-follow-this-pointer")
    config = tmp_path / "config"
    r = cli("setup", "--repo", root, "--name", "test", "--config-dir", config)
    assert r.returncode == 1
    assert json.loads(r.stdout)["code"] == "LINKED_WORKTREE_UNSUPPORTED"
    assert not config.exists()


def test_setup_does_not_follow_policy_symlink(repo, tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    target = tmp_path / "external"
    target.write_text(SECRET)
    (config / "test.toml").symlink_to(target)
    r = cli("setup", "--repo", repo.root, "--name", "test", "--config-dir", config)
    assert r.returncode == 1
    assert json.loads(r.stdout)["code"] == "POLICY_CONFLICT"
    assert target.read_text() == SECRET
    assert SECRET not in r.stdout + r.stderr


@pytest.mark.parametrize("symlink", [False, True])
def test_setup_fails_if_new_policy_path_appears_during_preflight(
    repo, tmp_path, monkeypatch, symlink
):
    import safe_git_mcp.deployment as deployment

    config = tmp_path / "config"
    config.mkdir()
    target = tmp_path / "existing-policy.toml"
    content = f'repository_root="{repo.root}"\nmax_commits=7\n'
    target.write_text(content)
    path = config / "racing.toml"
    real_check = deployment.check_repository

    def concurrent_creation(policy):
        real_check(policy)
        if symlink:
            path.symlink_to(target)
        else:
            path.write_text(content)

    monkeypatch.setattr(deployment, "check_repository", concurrent_creation)
    with pytest.raises(deployment.DeploymentError) as error:
        deployment.setup(repo.root, "racing", config, "eltex-claude", False)
    assert error.value.code == "POLICY_WRITE_FAILED"
    assert path.read_text() == content
    assert target.read_text() == content


def test_doctor_expands_quoted_tilde_policy_path(repo, tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(f'repository_root="{repo.root}"\n')
    r = cli("doctor", "--policy", "~/config.toml", env={**os.environ, "HOME": str(tmp_path)})
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(r.stdout)["code"] == "READY"


def test_handshake_errors_never_disclose_exception_text(tmp_path, monkeypatch):
    import safe_git_mcp.deployment as deployment

    async def broken(_):
        raise RuntimeError(SECRET)

    monkeypatch.setattr(deployment, "_handshake", broken)
    with pytest.raises(deployment.DeploymentError) as error:
        deployment.handshake(tmp_path / "policy.toml")
    assert error.value.code == "MCP_CONNECTION_FAILED"
    assert SECRET not in str(error.value)


def test_setup_preserves_malformed_existing_policy(repo, tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    p = config / "test.toml"
    p.write_text(SECRET)
    r = cli("setup", "--repo", repo.root, "--name", "test", "--config-dir", config)
    assert r.returncode == 1
    assert json.loads(r.stdout)["code"] == "POLICY_CONFLICT"
    assert p.read_text() == SECRET
    assert SECRET not in r.stdout + r.stderr


@pytest.mark.parametrize("command", ["doctor", "setup"])
def test_project_denies_invalid_startup_is_diagnosed_before_setup_writes(repo, tmp_path, command):
    env = {**os.environ, "SAFE_GIT_PROJECT_DENY_PATHS": SECRET}
    config = tmp_path / "new-config"
    args = (
        ["--policy", policy_file(repo, tmp_path)]
        if command == "doctor"
        else ["--repo", repo.root, "--name", "demo", "--config-dir", config]
    )
    r = cli(command, *args, env=env)
    assert r.returncode == 1
    assert json.loads(r.stdout)["code"] == "PROJECT_DENIES_INVALID"
    assert SECRET not in r.stdout + r.stderr
    assert not config.exists()


def test_setup_does_not_persist_runtime_project_rules(repo, tmp_path):
    config = tmp_path / "config"
    env = {**os.environ, "SAFE_GIT_PROJECT_DENY_PATHS": '["internal/**"]'}
    r = cli("setup", "--repo", repo.root, "--name", "demo", "--config-dir", config, env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    policy = Policy.load(config / "demo.toml")
    assert policy.allows("internal/a")
    assert not policy.allows("env/private.config")


def test_server_rejects_invalid_project_env_without_echo(repo, tmp_path):
    policy = policy_file(repo, tmp_path)
    r = cli("--policy", policy, env={**os.environ, "SAFE_GIT_PROJECT_DENY_PATHS": SECRET})
    assert r.returncode == 1
    assert SECRET not in r.stdout + r.stderr


def test_doctor_handshake_child_receives_project_startup_env(repo, tmp_path, monkeypatch):
    from safe_git_mcp.deployment import DeploymentError, handshake

    monkeypatch.setenv("SAFE_GIT_PROJECT_DENY_PATHS", SECRET)
    with pytest.raises(DeploymentError) as error:
        handshake(policy_file(repo, tmp_path))
    assert error.value.code == "MCP_CONNECTION_FAILED"
    assert SECRET not in str(error.value)
