"""Real runtime checks. Explicit opt-in; CI builds the image and enables these."""

import json
import os
import subprocess
from contextlib import asynccontextmanager

import pytest
from conftest import SECRET
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

pytestmark = pytest.mark.skipif(
    os.environ.get("SAFE_GIT_DOCKER_TESTS") != "1",
    reason="Docker integration requires SAFE_GIT_DOCKER_TESTS=1 and built image",
)
IMAGE = os.environ.get("SAFE_GIT_DOCKER_IMAGE", "safe-git-mcp:test")


def arguments(root, policy):
    return [
        "run",
        "--rm",
        "-i",
        "--network=none",
        "--env",
        "HTTP_PROXY=",
        "--env",
        "HTTPS_PROXY=",
        "--env",
        "ALL_PROXY=",
        "--env",
        "NO_PROXY=",
        "--env",
        "http_proxy=",
        "--env",
        "https_proxy=",
        "--env",
        "all_proxy=",
        "--env",
        "no_proxy=",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--pids-limit=64",
        "--memory=256m",
        "--cpus=1",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=16m,mode=1777",
        "--mount",
        f"type=bind,src={root},dst=/repo,readonly,bind-recursive=readonly,bind-propagation=rprivate",
        "--mount",
        f"type=bind,src={policy},dst=/policy/policy.toml,readonly",
    ]


@asynccontextmanager
async def container_client(repo, tmp_path):
    policy = tmp_path / "docker-policy.toml"
    policy.write_text('repository_root="/repo"\n')
    with (tmp_path / "docker-stderr").open("w+") as errors:
        async with stdio_client(
            StdioServerParameters(command="docker", args=[*arguments(repo.root, policy), IMAGE]),
            errlog=errors,
        ) as streams:
            async with ClientSession(*streams, read_timeout_seconds=20) as session:
                await session.initialize()
                yield session
        errors.seek(0)
        assert SECRET not in errors.read()


async def test_docker_official_stdio_client_filters_fake_secrets(repo, tmp_path):
    async with container_client(repo, tmp_path) as session:
        tools = await session.list_tools()
        assert len(tools.tools) == 6
        r = await session.call_tool("git_show_commit", {"commit": "HEAD"})
        assert not r.is_error
        assert [f["path"] for f in r.structured_content["files"]] == ["apps/core/src/routing.erl"]
        assert "+route() -> new." in r.structured_content["files"][0]["patch"]
        assert SECRET not in r.model_dump_json()
        r = await session.call_tool("git_file_history", {"path": "env/production.config"})
        assert r.is_error
        assert r.structured_content["error"]["code"] == "ACCESS_DENIED"
        assert SECRET not in r.model_dump_json()


def test_docker_runtime_restricts_writes_and_capabilities(repo, tmp_path):
    policy = tmp_path / "policy.toml"
    policy.write_text('repository_root="/repo"\n')
    script = """
import json,os,pathlib,socket
assert os.getuid() != 0
for path in ['/repo/apps/core/src/routing.erl','/policy/policy.toml','/opt/image-write-test']:
    try:
        with open(path,'a') as stream: stream.write('forbidden-write')
    except OSError: pass
    else: raise AssertionError('write unexpectedly allowed')
status=pathlib.Path('/proc/self/status').read_text()
assert 'CapEff:\\t0000000000000000' in status
assert 'NoNewPrivs:\\t1' in status
assert len(pathlib.Path('/proc/net/route').read_text().splitlines()) == 1
assert not pathlib.Path('/var/run/docker.sock').exists()
assert not pathlib.Path('/run/secrets/build_ca').exists()
assert not pathlib.Path('/tmp/apt-ca.conf').exists()
assert not any(value for key,value in os.environ.items() if key.upper() in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY'))
assert not pathlib.Path('/opt/safe-git/src').exists()
print(json.dumps({'uid':os.getuid(),'ok':True}))
"""
    r = subprocess.run(
        ["docker", *arguments(repo.root, policy), "--entrypoint", "python", IMAGE, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(r.stdout)["uid"] == os.getuid()
    assert SECRET not in r.stdout + r.stderr
    assert "forbidden-write" not in (repo.root / "apps/core/src/routing.erl").read_text()


def test_docker_doctor_rejects_linked_pointer_without_following_it(tmp_path):
    root = tmp_path / "linked"
    root.mkdir()
    (root / ".git").write_text("gitdir: /unmounted-original/" + SECRET)
    policy = tmp_path / "policy.toml"
    policy.write_text('repository_root="/repo"\n')
    r = subprocess.run(
        ["docker", *arguments(root, policy), IMAGE, "doctor", "--policy", "/policy/policy.toml"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r.returncode == 1
    assert json.loads(r.stdout)["code"] == "LINKED_WORKTREE_UNSUPPORTED"
    assert SECRET not in r.stdout + r.stderr


def test_docker_default_image_user_is_unprivileged():
    r = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--entrypoint",
            "python",
            IMAGE,
            "-c",
            "import os,json; print(json.dumps([os.getuid(),os.getgid()]))",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(r.stdout) == [10001, 10001]


def test_docker_doctor_confirms_real_stdio_readiness(repo, tmp_path):
    policy = tmp_path / "policy.toml"
    policy.write_text('repository_root="/repo"\n')
    r = subprocess.run(
        [
            "docker",
            *arguments(repo.root, policy),
            IMAGE,
            "doctor",
            "--policy",
            "/policy/policy.toml",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(r.stdout)["code"] == "READY"
    assert SECRET not in r.stdout + r.stderr
