"""Opt-in real Compose tests; fixtures contain only fake data."""

import json
import os
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from conftest import SECRET
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

pytestmark = pytest.mark.skipif(
    os.environ.get("SAFE_GIT_DOCKER_TESTS") != "1",
    reason="Requires Docker/Compose and built test image; opt in explicitly",
)
ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "compose.yaml"


def environment():
    # Test per-project env-file behavior independently of the caller's shell settings.
    return {
        k: v
        for k, v in os.environ.items()
        if k not in {"PROJECT_ROOT", "POLICY_FILE", "HOST_UID", "HOST_GID", "SAFE_GIT_IMAGE"}
    }


def prepare(repo, tmp_path, *, missing_repo=False, missing_variable=False):
    policy = tmp_path / "policy with spaces.toml"
    policy.write_text('repository_root="/repo"\n')
    envfile = tmp_path / "project with spaces.env"
    root = repo.root if not missing_repo else tmp_path / "does-not-exist"
    text = (
        f"POLICY_FILE='{policy}'\nHOST_UID={os.getuid()}\nHOST_GID={os.getgid()}\n"
        f"SAFE_GIT_IMAGE='{os.environ.get('SAFE_GIT_DOCKER_IMAGE', 'safe-git-mcp:test')}'\n"
        f"UNRELATED_SECRET='{SECRET}'\n"
    )
    if not missing_variable:
        text += f"PROJECT_ROOT='{root}'\n"
    envfile.write_text(text)
    return [
        "compose",
        "--project-name",
        "safe-git-compose-tests",
        "--file",
        str(COMPOSE),
        "--env-file",
        str(envfile),
    ]


@asynccontextmanager
async def client(repo, tmp_path):
    args = prepare(repo, tmp_path)
    with (tmp_path / "compose-stderr").open("w+") as errors:
        async with stdio_client(
            StdioServerParameters(
                command="docker",
                args=[*args, "run", "--rm", "--no-deps", "-T", "--interactive", "safe-git"],
                env=environment(),
            ),
            errlog=errors,
        ) as streams:
            async with ClientSession(*streams, read_timeout_seconds=25) as session:
                await session.initialize()
                yield session
        errors.seek(0)
        assert SECRET not in errors.read()


async def test_compose_official_client_filters_fake_secrets(repo, tmp_path):
    async with client(repo, tmp_path) as session:
        tools = await session.list_tools()
        assert len(tools.tools) == 6
        r = await session.call_tool("git_show_commit", {"commit": "HEAD"})
        assert not r.is_error
        assert [f["path"] for f in r.structured_content["files"]] == ["apps/core/src/routing.erl"]
        assert "+route() -> new." in r.structured_content["files"][0]["patch"]
        assert SECRET not in r.model_dump_json()
        denied = await session.call_tool("git_file_history", {"path": "env/production.config"})
        assert denied.is_error
        assert denied.structured_content["error"]["code"] == "ACCESS_DENIED"
        assert SECRET not in denied.model_dump_json()


def test_compose_runtime_mounts_env_and_restrictions(repo, tmp_path):
    script = """
import json,os,pathlib
assert os.getuid() != 0
assert 'UNRELATED_SECRET' not in os.environ
assert 'PROJECT_ROOT' not in os.environ
assert 'POLICY_FILE' not in os.environ
assert not any(v for k,v in os.environ.items() if k.upper() in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY'))
for name in ['/repo/apps/core/src/routing.erl','/policy/policy.toml','/opt/no-write']:
    try:
        with open(name,'a') as f: f.write('forbidden-write')
    except OSError: pass
    else: raise AssertionError('unexpected write')
status=pathlib.Path('/proc/self/status').read_text()
assert 'CapEff:\\t0000000000000000' in status
assert 'NoNewPrivs:\\t1' in status
assert len(pathlib.Path('/proc/net/route').read_text().splitlines())==1
assert not pathlib.Path('/var/run/docker.sock').exists()
print(json.dumps({'uid':os.getuid(),'ok':True}))
"""
    args = prepare(repo, tmp_path)
    r = subprocess.run(
        [
            "docker",
            *args,
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "--entrypoint",
            "python",
            "safe-git",
            "-c",
            script,
        ],
        capture_output=True,
        text=True,
        timeout=30,
        env=environment(),
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(r.stdout)["uid"] == os.getuid()
    assert SECRET not in r.stdout + r.stderr
    assert "forbidden-write" not in (repo.root / "apps/core/src/routing.erl").read_text()


def test_compose_doctor(repo, tmp_path):
    args = prepare(repo, tmp_path)
    r = subprocess.run(
        [
            "docker",
            *args,
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "safe-git",
            "doctor",
            "--policy",
            "/policy/policy.toml",
        ],
        capture_output=True,
        text=True,
        timeout=35,
        env=environment(),
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(r.stdout)["code"] == "READY"
    assert SECRET not in r.stdout + r.stderr


def test_compose_requires_project_root(repo, tmp_path):
    args = prepare(repo, tmp_path, missing_variable=True)
    r = subprocess.run(
        ["docker", *args, "config", "--format", "json"],
        capture_output=True,
        text=True,
        timeout=15,
        env=environment(),
    )
    assert r.returncode != 0
    assert "PROJECT_ROOT" in r.stderr


def test_compose_does_not_create_missing_mount_source(repo, tmp_path):
    args = prepare(repo, tmp_path, missing_repo=True)
    r = subprocess.run(
        [
            "docker",
            *args,
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "safe-git",
            "doctor",
            "--policy",
            "/policy/policy.toml",
        ],
        capture_output=True,
        text=True,
        timeout=20,
        env=environment(),
    )
    assert r.returncode != 0
    assert not (tmp_path / "does-not-exist").exists()


def test_project_env_files_are_ignored_and_example_is_trackable():
    paths = [".env", ".env.project-a", "project-a.env", "private/.env.example", ".env.example"]
    r = subprocess.run(
        ["git", "check-ignore", "--no-index", "--stdin"],
        cwd=ROOT,
        input="\n".join(paths) + "\n",
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0
    assert set(r.stdout.splitlines()) == set(paths[:-1])


async def test_two_project_env_files_keep_repository_bindings_separate(repo, tmp_path):
    from conftest import Repo

    second_root = tmp_path / "second project"
    second_root.mkdir()
    second = Repo(second_root)
    second.git("init", "-q", "-b", "main")
    second.write("README.md", "Second project content\n")
    second.write("env/private.config", SECRET + "\n")
    second.commit()
    a, b = tmp_path / "config-a", tmp_path / "config-b"
    a.mkdir()
    b.mkdir()
    async with client(repo, a) as first, client(second, b) as other:
        result_a = await first.call_tool("git_show_commit", {"commit": "HEAD"})
        result_b = await other.call_tool("git_show_commit", {"commit": "HEAD"})
        assert not result_a.is_error and not result_b.is_error
        assert [f["path"] for f in result_a.structured_content["files"]] == [
            "apps/core/src/routing.erl"
        ]
        assert [f["path"] for f in result_b.structured_content["files"]] == ["README.md"]
        assert "+Second project content" in result_b.structured_content["files"][0]["patch"]
        assert SECRET not in result_a.model_dump_json() + result_b.model_dump_json()


def test_compose_engine_receives_readonly_and_resource_limits(repo, tmp_path):
    args = prepare(repo, tmp_path)
    args[args.index("--project-name") + 1] = "safe-git-compose-options-test"

    def run(*parts):
        return subprocess.run(
            ["docker", *args, *parts], capture_output=True, text=True, timeout=25, env=environment()
        )

    try:
        created = run("create", "--no-build", "safe-git")
        assert created.returncode == 0, created.stdout + created.stderr
        ids = run("ps", "--all", "--quiet", "safe-git")
        assert ids.returncode == 0
        container_id = ids.stdout.strip()
        assert container_id and "\n" not in container_id
        info = json.loads(subprocess.check_output(["docker", "inspect", container_id], text=True))[
            0
        ]
        host = info["HostConfig"]
        assert host["ReadonlyRootfs"]
        assert host["NetworkMode"] == "none"
        assert host["CapDrop"] == ["ALL"]
        assert any(x.startswith("no-new-privileges") for x in host["SecurityOpt"])
        assert host["PidsLimit"] == 64
        assert host["Memory"] == 268435456
        assert host["NanoCpus"] == 1000000000
        options = set(host["Tmpfs"]["/tmp"].split(","))
        assert {"noexec", "nosuid", "mode=1777"} <= options
        assert options & {"size=16m", "size=16777216"}
        mounts = {m["Target"]: m for m in host["Mounts"]}
        assert set(mounts) == {"/repo", "/policy/policy.toml"}
        assert all(m["ReadOnly"] for m in mounts.values())
        assert mounts["/repo"]["BindOptions"]["Propagation"] == "rprivate"
        assert mounts["/repo"]["BindOptions"]["ReadOnlyForceRecursive"]
        assert info["Config"]["User"] == f"{os.getuid()}:{os.getgid()}"
        assert not info["Config"]["Tty"] and info["Config"]["OpenStdin"]
        assert SECRET not in json.dumps(info["Config"]["Env"])
    finally:
        removed = run("rm", "--stop", "--force", "safe-git")
        assert removed.returncode == 0, removed.stdout + removed.stderr
