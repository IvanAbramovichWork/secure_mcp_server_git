from pathlib import Path

import pytest

from safe_git_mcp.config import Policy
from safe_git_mcp.errors import SafeError
from safe_git_mcp.policy import is_allowed_git_path


@pytest.mark.parametrize(
    "path",
    [
        "env/production.config",
        "root/etc/ecss/a",
        "apps/sorm/src/x.erl",
        "apps/sorm_adapter/src/x.erl",
        "apps/lpm_test/a",
        "apps/ecss_storekeeper/config/a",
        "_deps/ecss_license_agent/a",
        "x.pem",
        "a/b.pem",
        ".env",
        "a/.env.local",
        "a/.erlang.cookie",
        ".erlang.crypt",
        ".mcp.json",
        "a/settings.local.json",
        ".claude/settings.json",
        "a/x.secret.exs",
        "../env/a",
        "/tmp/a",
        "a//b",
        "a/../b",
        "a/./b",
        "a\x00b",
        ":(glob)**",
        b"a/\xff",
        "",
        "a\\b",
    ],
)
def test_denied_paths(path):
    assert not is_allowed_git_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "apps/core/src/routing.erl",
        "README.md",
        "a space/file\nname.erl",
        "apps/ядро.erl",
        ".env.example",
    ],
)
def test_safe_paths(path):
    assert is_allowed_git_path(path, exceptions=(".env.example",))


def test_case_sensitive_and_component_globs():
    assert is_allowed_git_path("ENV/a")
    assert is_allowed_git_path("other/env/a")
    assert not is_allowed_git_path("a/b/key.pem")
    assert is_allowed_git_path("apps/core/a", mode="allowlist", allow=("apps/core/**",))
    assert not is_allowed_git_path("new/app/a", mode="allowlist", allow=("apps/core/**",))
    assert not is_allowed_git_path("env/a", exceptions=("env/**",))


def test_invalid_policy_refuses_startup(tmp_path):
    for text in [
        "",
        'repository_root="relative"',
        'repository_root="/tmp"\nmax_commits=0',
        'repository_root="/tmp"\nreturn_commit_messages=true',
        'repository_root="/tmp"\nunknown=true',
    ]:
        p = tmp_path / "policy.toml"
        p.write_text(text)
        with pytest.raises(SafeError):
            Policy.load(p)
    with pytest.raises(SafeError):
        Policy.load(tmp_path / "missing")


def test_valid_policy(tmp_path):
    p = tmp_path / "policy.toml"
    p.write_text(f'repository_root="{tmp_path}"\n')
    policy = Policy.load(p)
    assert policy.repository_root == Path(tmp_path)
    assert policy.max_context_lines == 10


@pytest.mark.parametrize(
    "key", ["deny_paths", "allow_paths", "allow_exceptions", "quarantine_literals"]
)
@pytest.mark.parametrize("value", ['"env"', '{env="**"}'])
def test_policy_list_fields_reject_string_and_table(tmp_path, key, value):
    p = tmp_path / "policy.toml"
    p.write_text(f'repository_root="{tmp_path}"\n{key}={value}\n')
    with pytest.raises(SafeError):
        Policy.load(p)
