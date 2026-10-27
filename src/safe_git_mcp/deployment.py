"""Operator-only setup/diagnostics; never exposed as MCP tools."""

import asyncio
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from .audit import TOOLS
from .backend import Backend
from .config import Policy

MESSAGES = {
    "READY": "Policy, repository initialization and MCP stdio handshake passed.",
    "POLICY_INVALID": "Policy missing, unreadable or invalid. Use an absolute repository_root, not ~.",
    "GIT_MISSING": "Git must be available in /usr/bin or /bin.",
    "PRLIMIT_MISSING": "Install util-linux: /usr/bin/prlimit must be executable.",
    "REPO_MISSING": "Configured repository directory is missing or inaccessible.",
    "LINKED_WORKTREE_UNSUPPORTED": "Linked worktree detected. This version requires an independently approved main checkout or standalone clone. Do not edit the .git pointer; setup will not redirect to shared history.",
    "GIT_LAYOUT_UNSUPPORTED": "An owned non-bare checkout with a .git directory is required.",
    "REPOSITORY_REJECTED": "Repository initialization rejected. Check ownership, local Git config, shallow state, replace refs, grafts and alternates. Do not weaken those checks.",
    "MCP_CONNECTION_FAILED": "MCP stdio handshake failed. Run the synthetic MCP integration tests.",
    "INVALID_NAME": "Use a project name starting with a letter, followed by letters, digits, _ or - (64 characters maximum).",
    "POLICY_CONFLICT": "An existing policy has a different binding or is invalid. It was not overwritten. Choose a different name or review that policy.",
    "POLICY_WRITE_FAILED": "Could not create the policy safely. Existing files were not overwritten.",
    "CLIENT_REGISTRATION_FAILED": "Client registration failed. The policy is retained. Run setup without --register to print the command; check client availability and existing registrations.",
    "SETUP_FAILED": "Setup could not complete. No raw exception or subprocess output is disclosed.",
}


class DeploymentError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(MESSAGES[code])


def load_policy(path: Path) -> Policy:
    try:
        return Policy.load(path.expanduser().absolute())
    except Exception:
        raise DeploymentError("POLICY_INVALID") from None


def check_repository(policy: Policy) -> None:
    if not shutil.which("git", path="/usr/bin:/bin"):
        raise DeploymentError("GIT_MISSING")
    if not os.access("/usr/bin/prlimit", os.X_OK):
        raise DeploymentError("PRLIMIT_MISSING")
    root = policy.repository_root
    if not root.is_dir():
        raise DeploymentError("REPO_MISSING")
    gitdir = root / ".git"
    # Do not open pointer files or follow their targets to the original repository.
    if gitdir.is_file() and not gitdir.is_symlink():
        raise DeploymentError("LINKED_WORKTREE_UNSUPPORTED")
    if gitdir.is_symlink() or not gitdir.is_dir():
        raise DeploymentError("GIT_LAYOUT_UNSUPPORTED")
    try:
        Backend(policy)
    except Exception:
        raise DeploymentError("REPOSITORY_REJECTED") from None


async def _handshake(policy: Path) -> None:
    with tempfile.TemporaryFile(mode="w+") as errors:
        async with stdio_client(
            StdioServerParameters(
                command=sys.executable,
                args=["-m", "safe_git_mcp", "--policy", str(policy)],
            ),
            errlog=errors,
        ) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                result = await session.list_tools()
                if {tool.name for tool in result.tools} != TOOLS:
                    raise DeploymentError("MCP_CONNECTION_FAILED")


def handshake(policy: Path) -> None:
    try:
        asyncio.run(asyncio.wait_for(_handshake(policy), timeout=15))
    except Exception:
        raise DeploymentError("MCP_CONNECTION_FAILED") from None


def doctor(path: Path) -> dict[str, object]:
    path = path.expanduser().absolute()
    check_repository(load_policy(path))
    handshake(path)
    return {"ok": True, "code": "READY", "message": MESSAGES["READY"]}


def setup(
    repo: Path, name: str, config_dir: Path, client: str, register: bool
) -> dict[str, object]:
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", name):
        raise DeploymentError("INVALID_NAME")
    root = repo.expanduser().absolute()
    config_dir = config_dir.expanduser().absolute()
    path = config_dir / f"{name}.toml"
    if path.is_symlink():
        raise DeploymentError("POLICY_CONFLICT")
    create_policy = not path.exists()
    if not create_policy:
        try:
            policy = load_policy(path)
            if policy.repository_root != root:
                raise DeploymentError("POLICY_CONFLICT")
        except DeploymentError:
            raise DeploymentError("POLICY_CONFLICT") from None
    else:
        policy = Policy(
            repository_root=root,
            quarantine_literals=(
                "-----BEGIN PRIVATE KEY-----",
                "ECSS10_TEST_SECRET_DO_NOT_EXPOSE_",
            ),
        )
    check_repository(policy)
    if create_policy:
        content = "# Generated local prototype policy. Review rules before use.\n"
        for key, value in policy.model_dump(mode="json").items():
            content += f"{key} = {json.dumps(value, ensure_ascii=False)}\n"
        try:
            config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(content)
        except Exception:
            raise DeploymentError("POLICY_WRITE_FAILED") from None
    handshake(path)
    argv = [
        client,
        "mcp",
        "add",
        "--transport",
        "stdio",
        "--scope",
        "user",
        f"safe-git-{name}",
        "--",
        str(Path(sys.executable).absolute()),
        "-m",
        "safe_git_mcp",
        "--policy",
        str(path),
    ]
    if register:
        try:
            # The operator explicitly requests this write to client configuration.
            # Suppress client output, which may contain private settings or credentials.
            subprocess.run(
                argv,
                check=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
                shell=False,
            )
        except Exception:
            raise DeploymentError("CLIENT_REGISTRATION_FAILED") from None
    return {
        "ok": True,
        "code": "READY",
        "message": MESSAGES["READY"],
        "policy": str(path),
        "registered": register,
        "registration_argv": argv,
        "registration_command": shlex.join(argv),
        "notice": "Local stdio prototype: requires separate OS isolation for confidential data.",
    }
