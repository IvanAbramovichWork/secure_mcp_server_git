import pytest

from safe_git_mcp.backend import Backend
from safe_git_mcp.config import Policy
from safe_git_mcp.errors import SafeError


@pytest.mark.parametrize(
    "ref",
    [
        "HEAD:env/production.config",
        "--all",
        "-p",
        "-c",
        "HEAD~1",
        "HEAD^{tree}",
        "a..b",
        "HEAD@{1}",
        "$(id)",
        "x\x00y",
        "",
        "x" * 257,
    ],
)
def test_revision_injection(repo, ref):
    b = Backend(Policy(repository_root=repo.root))
    with pytest.raises(SafeError) as e:
        b.resolve(ref)
    assert e.value.code == "INVALID_REF"


def test_supported_refs(repo):
    sha = repo.git("rev-parse", "HEAD")
    repo.git("tag", "-am", "private annotation", "v1")
    b = Backend(Policy(repository_root=repo.root))
    for ref in ["HEAD", "main", "v1", "refs/heads/main", sha]:
        assert b.resolve(ref) == sha
    repo.git("checkout", "--detach", "-q")
    assert b.resolve("HEAD") == sha


def test_ambiguous_branch_and_tag_fail_closed(repo):
    repo.git("tag", "main")
    with pytest.raises(SafeError) as e:
        Backend(Policy(repository_root=repo.root)).resolve("main")
    assert e.value.code == "INVALID_REF"


def test_noncommit_ref(repo):
    blob = repo.git("rev-parse", "HEAD:apps/core/src/routing.erl")
    with pytest.raises(SafeError) as e:
        Backend(Policy(repository_root=repo.root)).resolve(blob)
    assert e.value.code == "INVALID_REF"
