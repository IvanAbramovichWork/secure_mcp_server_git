import json
import sys
from contextlib import asynccontextmanager

import pytest
from conftest import SECRET
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


@asynccontextmanager
async def client(repo, tmp_path, *, max_response_bytes=1048576):
    policy = tmp_path / "policy.toml"
    policy.write_text(
        f'repository_root = "{repo.root}"\nmax_response_bytes = {max_response_bytes}\n'
    )
    stderr = tmp_path / "server-stderr"
    with stderr.open("w+") as errors:
        async with stdio_client(
            StdioServerParameters(
                command=sys.executable, args=["-m", "safe_git_mcp", "--policy", str(policy)]
            ),
            errlog=errors,
        ) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                yield session
        errors.seek(0)
        assert SECRET not in errors.read()


async def test_stdio_tools_and_filtered_response(repo, tmp_path):
    async with client(repo, tmp_path) as session:
        tools = await session.list_tools()
        assert {t.name for t in tools.tools} == {
            "git_log",
            "git_diff",
            "git_show_commit",
            "git_file_history",
            "git_changed_files",
            "git_blame",
        }
        for t in tools.tools:
            assert t.output_schema
            assert "repo_path" not in t.input_schema["properties"]
            assert SECRET not in t.model_dump_json()
        result = await session.call_tool("git_show_commit", {"commit": "HEAD"})
        assert not result.is_error
        data = result.structured_content
        assert data["files"][0]["path"] == "apps/core/src/routing.erl"
        assert "+route() -> new." in data["files"][0]["patch"]
        assert SECRET not in result.model_dump_json()
        for name, args in [
            ("git_log", {}),
            ("git_file_history", {"path": "apps/core/src/routing.erl"}),
            ("git_diff", {"base": repo.git("rev-parse", "HEAD^"), "head": "HEAD"}),
            ("git_changed_files", {"base": repo.git("rev-parse", "HEAD^"), "head": "HEAD"}),
            ("git_blame", {"path": "apps/core/src/routing.erl", "start_line": 1, "end_line": 1}),
        ]:
            r = await session.call_tool(name, args)
            assert r.structured_content["error"] is None
            assert SECRET not in r.model_dump_json()


@pytest.mark.parametrize(
    "name,args,code",
    [
        ("git_show_commit", {"commit": "HEAD:env/production.config"}, "INVALID_REF"),
        ("git_file_history", {"path": "env/production.config"}, "ACCESS_DENIED"),
        ("git_show_commit", {"commit": "HEAD", "repo_path": SECRET}, "INVALID_INPUT"),
        ("git_log", {"limit": SECRET}, "INVALID_INPUT"),
        ("git_log", {"limit": True}, "INVALID_INPUT"),
        ("git_log", {"ref": {"private": SECRET}}, "INVALID_INPUT"),
        (SECRET, {}, "INVALID_INPUT"),
    ],
)
async def test_stdio_errors_never_echo_arguments(repo, tmp_path, name, args, code):
    async with client(repo, tmp_path) as session:
        r = await session.call_tool(name, args)
        assert r.is_error
        assert r.structured_content["error"]["code"] == code
        assert SECRET not in r.model_dump_json()
        assert "production.config" not in json.dumps(r.structured_content)


async def test_complete_mcp_envelope_is_bounded(repo, tmp_path):
    async with client(repo, tmp_path, max_response_bytes=1000) as session:
        result = await session.call_tool("git_show_commit", {"commit": "HEAD"})
        if result.is_error:
            assert result.structured_content["error"]["code"] == "OUTPUT_LIMIT"
        else:
            assert len(result.model_dump_json(by_alias=True, exclude_none=True).encode()) <= 1000
