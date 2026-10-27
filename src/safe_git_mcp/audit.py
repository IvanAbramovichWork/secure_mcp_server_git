"""Deliberately excludes paths, arguments, data, timestamps and exception text."""

import json
import sys

TOOLS = frozenset(
    {"git_log", "git_diff", "git_show_commit", "git_file_history", "git_changed_files", "git_blame"}
)
CODES = frozenset(
    {
        "OK",
        "ACCESS_DENIED",
        "INVALID_REF",
        "INVALID_PATH",
        "INVALID_INPUT",
        "OUTPUT_LIMIT",
        "TIMEOUT",
        "UNSUPPORTED_MERGE",
        "INTERNAL_ERROR",
    }
)


def event(tool: str, code: str) -> None:
    sys.stderr.write(
        json.dumps(
            {
                "tool": tool if tool in TOOLS else "unknown",
                "code": code if code in CODES else "INTERNAL_ERROR",
            }
        )
        + "\n"
    )
