"""Case-sensitive component globs: * and ? never cross /; ** spans zero or more components."""

import fnmatch
from functools import cache

DEFAULT_DENY = (
    "env/**",
    "root/etc/ecss/**",
    "apps/sorm*/**",
    "apps/lpm*/**",
    "apps/ecss_storekeeper/config/**",
    "_deps/ecss_license_agent/**",
    "**/*.pem",
    "**/*.secret.exs",
    "**/.env",
    "**/.env.*",
    "**/.erlang.cookie",
    "**/.erlang.crypt",
    ".mcp.json",
    "**/settings.local.json",
    ".claude/**",
)


def valid_path(path: bytes | str) -> str | None:
    try:
        value = path.decode("utf-8", "strict") if isinstance(path, bytes) else path
        value.encode("utf-8", "strict")
    except (UnicodeError, AttributeError):
        return None
    if (
        not value
        or len(value.encode()) > 4096
        or "\x00" in value
        or "\\" in value
        or value.startswith(("/", ":", "-"))
        or len(value.split("/")) > 128
        or any(p in ("", ".", "..", ".git") for p in value.split("/"))
    ):
        return None
    return value


def matches(path: str, pattern: str) -> bool:
    parts, pats = tuple(path.split("/")), tuple(pattern.split("/"))

    @cache
    def visit(i: int, j: int) -> bool:
        if j == len(pats):
            return i == len(parts)
        if pats[j] == "**":
            return visit(i, j + 1) or (i < len(parts) and visit(i + 1, j))
        return i < len(parts) and fnmatch.fnmatchcase(parts[i], pats[j]) and visit(i + 1, j + 1)

    return visit(0, 0)


def is_allowed_git_path(
    path: bytes | str,
    *,
    deny: tuple[str, ...] = DEFAULT_DENY,
    exceptions: tuple[str, ...] = (),
    mode: str = "denylist",
    allow: tuple[str, ...] = (),
) -> bool:
    value = valid_path(path)
    if value is None:
        return False
    if mode == "allowlist" and not any(matches(value, p) for p in allow):
        return False
    if mode not in ("denylist", "allowlist"):
        return False
    if value in exceptions and not any(c in value for c in "*?["):
        return True
    return not any(matches(value, p) for p in deny)
