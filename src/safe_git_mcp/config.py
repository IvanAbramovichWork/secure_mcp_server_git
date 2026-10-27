import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .errors import SafeError
from .policy import DEFAULT_DENY, is_allowed_git_path, valid_path


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    repository_root: Path
    policy_mode: Literal["denylist", "allowlist"] = "denylist"
    max_commits: int = Field(default=100, ge=1, le=1000)
    max_changed_files: int = Field(default=500, ge=1, le=5000)
    max_diff_bytes: int = Field(default=262144, ge=1, le=4194304)
    max_response_bytes: int = Field(default=1048576, ge=1, le=16777216)
    max_file_bytes: int = Field(default=131072, ge=1, le=4194304)
    max_context_lines: int = Field(default=10, ge=0, le=10)
    max_runtime_seconds: int = Field(default=8, ge=1, le=60)
    max_subprocesses: int = Field(default=2048, ge=1, le=10000)
    return_commit_messages: Literal[False] = False
    return_author_identity: Literal[False] = False
    deny_paths: tuple[str, ...] = DEFAULT_DENY
    allow_paths: tuple[str, ...] = ()
    allow_exceptions: tuple[str, ...] = ()
    quarantine_literals: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_policy(self) -> "Policy":
        if not self.repository_root.is_absolute():
            raise ValueError("Absolute root required")
        if len(self.quarantine_literals) > 64 or any(
            not s or len(s) > 256 for s in self.quarantine_literals
        ):
            raise ValueError("Invalid quarantine literal")
        for pattern in self.deny_paths + self.allow_paths:
            if (
                not valid_path(pattern)
                or "[" in pattern
                or len(pattern) > 256
                or len(pattern.split("/")) > 32
            ):
                raise ValueError("Unsupported pattern")
        for path in self.allow_exceptions:
            if not valid_path(path) or any(c in path for c in "*?["):
                raise ValueError("Exact exceptions required")
        if self.policy_mode == "allowlist" and not self.allow_paths:
            raise ValueError("Empty allowlist")
        return self

    def allows(self, path: bytes | str) -> bool:
        return is_allowed_git_path(
            path,
            deny=self.deny_paths,
            exceptions=self.allow_exceptions,
            mode=self.policy_mode,
            allow=self.allow_paths,
        )

    @classmethod
    def load(cls, path: Path) -> "Policy":
        try:
            if path.stat().st_size > 65536:
                raise ValueError
            data = tomllib.loads(path.read_text(encoding="utf-8"))
            data["repository_root"] = Path(data["repository_root"])
            for key in ("deny_paths", "allow_paths", "allow_exceptions", "quarantine_literals"):
                if key in data:
                    if not isinstance(data[key], list):
                        raise ValueError("Policy arrays required")
                    data[key] = tuple(data[key])
            return cls.model_validate(data)
        except Exception:
            raise SafeError() from None
