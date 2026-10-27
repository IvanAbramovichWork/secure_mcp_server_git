import logging
from collections.abc import Callable
from functools import partial
from typing import Annotated, Any

from mcp.server import MCPServer
from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.types import CallToolResult, TextContent
from pydantic import BaseModel, ConfigDict, Field

from .audit import event
from .config import Policy
from .errors import SafeError
from .history import History
from .models import Error, Result

Ref = Annotated[str, Field(strict=True, min_length=1, max_length=256)]
GitPath = Annotated[str, Field(strict=True, min_length=1, max_length=4096)]
Limit = Annotated[int, Field(strict=True, ge=1, le=1000)]
ContextLines = Annotated[int, Field(strict=True, ge=0, le=10)]
Line = Annotated[int, Field(strict=True, ge=1, le=1000000)]
Paths = Annotated[list[GitPath], Field(max_length=5000)]


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class LogRequest(Request):
    ref: Ref = "HEAD"
    limit: Limit = 20
    path: GitPath | None = None


class FileRequest(Request):
    path: GitPath
    ref: Ref = "HEAD"
    limit: Limit = 20


class DiffRequest(Request):
    base: Ref
    head: Ref
    paths: Paths | None = None
    context_lines: ContextLines = 3


class ShowRequest(Request):
    commit: Ref
    context_lines: ContextLines = 3


class ChangedRequest(Request):
    base: Ref
    head: Ref


class BlameRequest(Request):
    path: GitPath
    ref: Ref = "HEAD"
    start_line: Line = 1
    end_line: Line = 100


SCHEMAS: dict[str, type[Request]] = {
    "git_log": LogRequest,
    "git_file_history": FileRequest,
    "git_diff": DiffRequest,
    "git_show_commit": ShowRequest,
    "git_changed_files": ChangedRequest,
    "git_blame": BlameRequest,
}


def failure(code: str) -> CallToolResult:
    result = Result(error=Error(code=code))
    return CallToolResult(
        content=[TextContent(type="text", text=result.model_dump_json())],
        structured_content=result.model_dump(),
        is_error=True,
    )


async def guard(
    ctx: ServerRequestContext[Any, Any], call_next: CallNext, *, max_response_bytes: int = 1048576
) -> HandlerResult:
    """Validate before SDK validation, whose error text can contain rejected values."""
    name = "unknown"
    try:
        if ctx.method == "tools/call":
            params = ctx.params
            if not isinstance(params, dict) or not isinstance(params.get("name"), str):
                return failure("INVALID_INPUT")
            name = params["name"]
            schema = SCHEMAS.get(name)
            if schema is None or set(params) - {"name", "arguments", "_meta"}:
                event(name, "INVALID_INPUT")
                return failure("INVALID_INPUT")
            try:
                schema.model_validate(params.get("arguments") or {})
            except Exception:
                event(name, "INVALID_INPUT")
                return failure("INVALID_INPUT")
        result = await call_next(ctx)
        if ctx.method == "tools/call":
            # MCP v2 runner serializes handler results inside the middleware chain.
            if isinstance(result, dict):
                result = CallToolResult.model_validate(result)
            if not isinstance(result, CallToolResult) or not result.structured_content:
                event(name, "INTERNAL_ERROR")
                return failure("INTERNAL_ERROR")
            error = result.structured_content.get("error")
            code = error["code"] if error else "OK"
            if (
                not error
                and len(result.model_dump_json(by_alias=True, exclude_none=True).encode())
                > max_response_bytes
            ):
                event(name, "OUTPUT_LIMIT")
                return failure("OUTPUT_LIMIT")
            event(name, code)
            if error:
                return failure(code)
        return result
    except Exception:
        event(name, "INTERNAL_ERROR")
        return failure("INTERNAL_ERROR")


def perform(fn: Callable[[], Result]) -> Result:
    try:
        return fn()
    except SafeError as exc:
        return Result(error=Error(code=exc.code))
    except Exception:
        return Result(error=Error(code="INTERNAL_ERROR"))


def create_server(policy: Policy) -> MCPServer[None]:
    # SDK validation/debug logging must not echo client arguments or repository data.
    logging.disable(logging.CRITICAL)
    history = History(policy)
    server: MCPServer[None] = MCPServer(
        "safe-git",
        version="0.1.0",
        log_level="CRITICAL",
        middleware=[partial(guard, max_response_bytes=policy.max_response_bytes)],
    )

    @server.tool(description="Read approved commit IDs, timestamps and changed paths.")
    def git_log(ref: Ref = "HEAD", limit: Limit = 20, path: GitPath | None = None) -> Result:
        return perform(lambda: history.git_log(ref, limit, path))

    @server.tool(description="Compare two committed revisions, filtering paths before patches.")
    def git_diff(
        base: Ref, head: Ref, paths: Paths | None = None, context_lines: ContextLines = 3
    ) -> Result:
        return perform(lambda: history.git_diff(base, head, paths, context_lines))

    @server.tool(
        description="Read approved changes in one non-merge commit, including root commits."
    )
    def git_show_commit(commit: Ref, context_lines: ContextLines = 3) -> Result:
        return perform(lambda: history.git_show_commit(commit, context_lines))

    @server.tool(
        description="Read commit IDs and timestamps for one approved literal historical path."
    )
    def git_file_history(path: GitPath, ref: Ref = "HEAD", limit: Limit = 20) -> Result:
        return perform(lambda: history.git_file_history(path, ref, limit))

    @server.tool(description="List only approved regular files changed between two commits.")
    def git_changed_files(base: Ref, head: Ref) -> Result:
        return perform(lambda: history.git_changed_files(base, head))

    @server.tool(
        description="Read bounded approved historical lines and commit IDs without identities."
    )
    def git_blame(
        path: GitPath, ref: Ref = "HEAD", start_line: Line = 1, end_line: Line = 100
    ) -> Result:
        return perform(lambda: history.git_blame(path, ref, start_line, end_line))

    return server
