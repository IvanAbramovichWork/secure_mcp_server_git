import json

import pytest

from safe_git_mcp.config import Policy
from safe_git_mcp.errors import SafeError
from safe_git_mcp.history import History


def test_project_denies_are_immutable_and_additive(tmp_path):
    original = Policy(repository_root=tmp_path, allow_exceptions=(".env.example",))
    effective = original.with_project_denies('["apps/core/**", ".env.example"]')
    assert original.allows("apps/core/a.erl")
    assert original.allows(".env.example")
    assert not effective.allows("apps/core/a.erl")
    assert not effective.allows(".env.example")
    assert not effective.allows("env/private.config")
    assert effective.allows("README.md")
    assert effective.deny_paths == original.deny_paths
    assert effective.allow_exceptions == original.allow_exceptions
    assert effective.repository_root == original.repository_root
    assert effective.max_commits == original.max_commits


def test_empty_rules_do_not_remove_operator_or_previous_denies(tmp_path):
    p = Policy(repository_root=tmp_path).with_project_denies('["internal/**"]')
    for value in [None, "[]"]:
        q = p.with_project_denies(value)
        assert not q.allows("env/private.config")
        assert not q.allows("internal/a")
        assert q.allows("README.md")


def test_project_rules_do_not_broaden_allowlist(tmp_path):
    p = Policy(repository_root=tmp_path, policy_mode="allowlist", allow_paths=("apps/core/**",))
    p = p.with_project_denies('["apps/core/internal/**"]')
    assert p.allows("apps/core/public.erl")
    assert not p.allows("apps/core/internal/private.erl")
    assert not p.allows("other/a")


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "null",
        "{}",
        '"internal/**"',
        "[1]",
        "[true]",
        "[null]",
        "[{}]",
        '["/absolute/**"]',
        '["../escape"]',
        '["a//b"]',
        '["a[glob]"]',
        '["!env/**"]',
        '["' + "a" * 257 + '"]',
        '["' + ("a/" * 33) + 'x"]',
        '["a\\u0000b"]',
        json.dumps(["x"] * 129),
        " " * 65537,
        "[",
    ],
    ids=lambda raw: f"{len(raw)}-bytes",
)
def test_invalid_project_rules_fail_closed_without_echoing_input(tmp_path, raw):
    p = Policy(repository_root=tmp_path)
    with pytest.raises(SafeError) as error:
        p.with_project_denies(raw)
    assert str(error.value) == "Request could not be completed."


def test_valid_rule_limit_and_unicode_patterns(tmp_path):
    p = Policy(repository_root=tmp_path).with_project_denies(
        json.dumps(["проект/**"] + ["x"] * 127)
    )
    assert not p.allows("проект/a")
    assert p.allows("public/a")


def test_all_history_apis_use_project_denies(repo):
    repo.write("internal/private.txt", "PROJECT_TEST_SECRET_NOT_FOR_MCP\n")
    repo.write("public.txt", "safe public\n")
    repo.commit()
    p = Policy(repository_root=repo.root).with_project_denies('["internal/**"]')
    h = History(p)
    parent = repo.git("rev-parse", "HEAD^")
    for result in [
        h.git_log(),
        h.git_diff(parent, "HEAD"),
        h.git_show_commit("HEAD"),
        h.git_changed_files(parent, "HEAD"),
    ]:
        text = result.model_dump_json()
        assert "internal/private.txt" not in text
        assert "PROJECT_TEST_SECRET_NOT_FOR_MCP" not in text
        assert "public.txt" in text
    for call in [
        lambda: h.git_file_history("internal/private.txt"),
        lambda: h.git_blame("internal/private.txt", start_line=1, end_line=1),
    ]:
        with pytest.raises(SafeError) as error:
            call()
        assert error.value.code == "ACCESS_DENIED"


def test_toml_project_denies_survive_empty_runtime_rules(tmp_path):
    path = tmp_path / "policy.toml"
    path.write_text(f'repository_root="{tmp_path}"\nproject_deny_paths=["operator-private/**"]\n')
    p = Policy.load(path).with_project_denies("[]")
    assert not p.allows("operator-private/a")
    assert not p.allows("env/private.config")
    assert p.allows("public/a")


def test_invalid_rule_does_not_echo_fake_secret(tmp_path):
    p = Policy(repository_root=tmp_path)
    with pytest.raises(SafeError) as error:
        p.with_project_denies('["../PROJECT_TEST_SECRET_NOT_FOR_MCP"]')
    assert "PROJECT_TEST_SECRET_NOT_FOR_MCP" not in str(error.value)


def test_project_denied_blob_is_not_read_even_if_missing(repo):
    repo.write("internal/private.txt", "PROJECT_TEST_SECRET_NOT_FOR_MCP\n")
    repo.write("public.txt", "safe public\n")
    repo.commit()
    blob = repo.git("rev-parse", "HEAD:internal/private.txt")
    (repo.root / ".git/objects" / blob[:2] / blob[2:]).unlink()
    h = History(Policy(repository_root=repo.root).with_project_denies('["internal/**"]'))
    result = h.git_show_commit("HEAD")
    assert [f.path for f in result.files] == ["public.txt"]
    assert "+safe public" in result.files[0].patch


def test_explicit_project_denied_path_arguments_are_rejected(repo):
    h = History(Policy(repository_root=repo.root).with_project_denies('["internal/**"]'))
    for call in [
        lambda: h.git_log(path="internal/private.txt"),
        lambda: h.git_diff("HEAD", "HEAD", paths=["internal/private.txt"]),
    ]:
        with pytest.raises(SafeError) as error:
            call()
        assert error.value.code == "ACCESS_DENIED"
