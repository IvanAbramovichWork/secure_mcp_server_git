import json
import os

import pytest
from conftest import SECRET

from safe_git_mcp.config import Policy
from safe_git_mcp.errors import SafeError
from safe_git_mcp.history import History

PATH = "apps/core/src/routing.erl"


def service(repo, **limits):
    return History(Policy(repository_root=repo.root, **limits))


def test_mixed_commit_filtered_diff_and_metadata(repo):
    h = service(repo)
    parent, head = repo.git("rev-parse", "HEAD^"), repo.git("rev-parse", "HEAD")
    result = h.git_diff(parent, head)
    assert [(x.path, x.change_type) for x in result.files] == [(PATH, "M")]
    assert "-route() -> old." in result.files[0].patch
    assert "+route() -> new." in result.files[0].patch
    assert SECRET not in result.model_dump_json()
    assert "production.config" not in result.model_dump_json()
    shown = h.git_show_commit("HEAD")
    assert shown.parents == [parent]
    assert shown.files == result.files
    log = h.git_log()
    assert len(log.commits) == 2
    assert all(c.approved_paths_changed == [PATH] for c in log.commits)
    assert SECRET not in log.model_dump_json()
    assert "message" not in log.model_dump_json()


def test_root_and_file_history(repo):
    h = service(repo)
    root = repo.git("rev-list", "--max-parents=0", "HEAD")
    result = h.git_show_commit(root)
    assert result.parents == []
    assert result.files[0].change_type == "A"
    assert "+route() -> old." in result.files[0].patch
    assert len(h.git_file_history(PATH).commits) == 2


@pytest.mark.parametrize(
    "path,code",
    [
        ("env/production.config", "ACCESS_DENIED"),
        ("../env/a", "INVALID_PATH"),
        ("/etc/passwd", "INVALID_PATH"),
        ("a\x00b", "INVALID_PATH"),
        (":(glob)**", "INVALID_PATH"),
    ],
)
def test_path_rejected_before_git(repo, path, code):
    h = service(repo)
    # If policy validation invokes Git first this exhausted budget would mask the denial.
    h.backend.budget.calls = 0
    with pytest.raises(SafeError) as e:
        h.git_file_history(path)
    assert e.value.code == code


def test_merge_patch_rejected(repo):
    repo.git("checkout", "-qb", "side")
    repo.write("side.txt", "safe\n")
    repo.commit()
    repo.git("checkout", "-q", "main")
    repo.write("main.txt", "safe\n")
    repo.commit()
    repo.git("merge", "--no-ff", "-m", SECRET, "side")
    h = service(repo)
    with pytest.raises(SafeError) as e:
        h.git_show_commit("HEAD")
    assert e.value.code == "UNSUPPORTED_MERGE"
    assert h.git_log().commits


def test_unusual_literal_paths(repo):
    for path in ["space name.txt", "line\nbreak.txt", "юникод.txt", "a[glob].txt"]:
        repo.write(path, "safe unusual\n")
    parent = repo.git("rev-parse", "HEAD")
    head = repo.commit()
    result = service(repo).git_diff(parent, head)
    assert {x.path for x in result.files} == {
        "space name.txt",
        "line\nbreak.txt",
        "юникод.txt",
        "a[glob].txt",
    }
    assert all("+safe unusual" in x.patch for x in result.files)


def test_invalid_utf8_names_fail_closed(repo):
    path = os.fsencode(repo.root) + b"/invalid\xff"
    with open(path, "wb") as f:
        f.write(SECRET.encode())
    repo.commit()
    assert service(repo).git_show_commit("HEAD").files == []


def test_symlinks_and_submodule_never_dereferenced(repo):
    (repo.root / "link").symlink_to("/etc/passwd")
    sha = repo.git("rev-parse", "HEAD")
    repo.git("update-index", "--add", "--cacheinfo", f"160000,{sha},module")
    repo.git("add", "link")
    repo.git("commit", "-qm", "links")
    assert service(repo).git_show_commit("HEAD").files == []


def test_external_diff_and_textconv_not_executed(repo, tmp_path):
    marker = tmp_path / "executed"
    script = tmp_path / "driver"
    script.write_text(f'#!/bin/sh\ntouch "{marker}"\necho "{SECRET}"\n')
    script.chmod(0o755)
    repo.git("config", "diff.evil.command", str(script))
    repo.git("config", "diff.evil.textconv", str(script))
    repo.write(".gitattributes", "*.erl diff=evil\n")
    repo.write(PATH, "route() -> latest.\n")
    repo.commit()
    result = service(repo).git_show_commit("HEAD")
    assert any("+route() -> latest." in f.patch for f in result.files)
    assert not marker.exists()
    assert SECRET not in result.model_dump_json()


def test_binary_data_never_returned(repo):
    (repo.root / "binary.dat").write_bytes(b"\0" + SECRET.encode())
    repo.commit()
    result = service(repo).git_show_commit("HEAD")
    assert result.files[0].patch == ""
    assert result.files[0].binary
    assert SECRET not in result.model_dump_json()


def test_limits_fail_closed(repo):
    for limits in [{"max_diff_bytes": 10}, {"max_file_bytes": 5}, {"max_changed_files": 1}]:
        with pytest.raises(SafeError) as e:
            service(repo, **limits).git_show_commit("HEAD")
        assert e.value.code == "OUTPUT_LIMIT"
    for kwargs in [{"limit": 0}, {"limit": 101}, {"limit": True}]:
        with pytest.raises(SafeError):
            service(repo).git_log(**kwargs)
    with pytest.raises(SafeError):
        service(repo).git_show_commit("HEAD", context_lines=11)


def test_secret_in_allowed_content_is_documented_residual(repo):
    repo.write("allowed.txt", SECRET + "\n")
    repo.commit()
    assert SECRET in service(repo).git_show_commit("HEAD").model_dump_json()


def test_rename_from_protected_is_documented_residual(repo):
    repo.git("mv", "env/production.config", "allowed.txt")
    repo.commit()
    result = service(repo).git_show_commit("HEAD")
    assert [f.path for f in result.files] == ["allowed.txt"]
    assert SECRET in result.model_dump_json()


def test_empty_and_protected_only_commits(repo):
    repo.commit()
    assert service(repo).git_show_commit("HEAD").files == []
    repo.write("env/production.config", SECRET + "_only\n")
    repo.commit()
    assert service(repo).git_show_commit("HEAD").files == []
    assert len(service(repo).git_log().commits) == 2


def test_changed_files_and_blame(repo):
    h = service(repo)
    result = h.git_changed_files(repo.git("rev-parse", "HEAD^"), "HEAD")
    assert [(x.path, x.patch) for x in result.files] == [(PATH, "")]
    blame = h.git_blame(PATH, start_line=1, end_line=1)
    assert blame.lines[0].text == "route() -> new."
    assert blame.lines[0].line_no == 1
    assert blame.lines[0].commit == repo.git("rev-parse", "HEAD")
    assert SECRET not in json.dumps(blame.model_dump())


def test_optional_content_quarantine(repo):
    repo.write("allowed.txt", SECRET + "\n")
    repo.commit()
    h = service(repo, quarantine_literals=(SECRET,))
    with pytest.raises(SafeError) as e:
        h.git_show_commit("HEAD")
    assert e.value.code == "ACCESS_DENIED"
    assert SECRET not in str(e.value)
    with pytest.raises(SafeError):
        h.git_blame("allowed.txt", start_line=1, end_line=1)


def test_complete_response_has_byte_limit(repo):
    h = service(repo, max_response_bytes=64)
    with pytest.raises(SafeError) as e:
        h.git_log()
    assert e.value.code == "OUTPUT_LIMIT"


def test_diff_size_budget_is_aggregate(repo):
    for n in range(3):
        repo.write(f"file{n}.txt", "safe\n" * 10)
    repo.commit()
    with pytest.raises(SafeError) as e:
        service(repo, max_diff_bytes=240).git_show_commit("HEAD")
    assert e.value.code == "OUTPUT_LIMIT"


def test_working_tree_changes_are_not_history(repo):
    h = service(repo)
    repo.write(PATH, "uncommitted " + SECRET)
    repo.write("env/new-secret", SECRET)
    result = h.git_show_commit("HEAD")
    assert "+route() -> new." in result.files[0].patch
    assert SECRET not in result.model_dump_json()


def test_deleted_regular_file_is_safe(repo):
    (repo.root / PATH).unlink()
    repo.commit()
    result = service(repo).git_show_commit("HEAD")
    assert result.files[0].change_type == "D"
    assert "-route() -> new." in result.files[0].patch


def test_non_utf8_patch_fails_closed(repo):
    (repo.root / "allowed.bin").write_bytes(b"not utf8 \xff\n")
    repo.commit()
    with pytest.raises(SafeError):
        service(repo).git_show_commit("HEAD")
