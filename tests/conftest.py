import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

SECRET = "ECSS10_TEST_SECRET_DO_NOT_EXPOSE_12345"


@dataclass
class Repo:
    root: Path

    def git(self, *args: str) -> str:
        return (
            subprocess.check_output(
                ["git", "-C", str(self.root), *args],
                env={
                    **os.environ,
                    "GIT_CONFIG_GLOBAL": "/dev/null",
                    "GIT_CONFIG_SYSTEM": "/dev/null",
                    "GIT_AUTHOR_NAME": "Synthetic",
                    "GIT_AUTHOR_EMAIL": "test@example.invalid",
                    "GIT_COMMITTER_NAME": "Synthetic",
                    "GIT_COMMITTER_EMAIL": "test@example.invalid",
                },
                stderr=subprocess.PIPE,
            )
            .decode()
            .strip()
        )

    def write(self, path: str, text: str) -> None:
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def commit(self, message: str = "synthetic") -> str:
        self.git("add", "--all")
        self.git("commit", "-qm", message, "--allow-empty")
        return self.git("rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "synthetic"
    root.mkdir()
    r = Repo(root)
    r.git("init", "-q", "-b", "main")
    r.write("apps/core/src/routing.erl", "route() -> old.\n")
    r.write("env/production.config", SECRET + "\n")
    r.commit(SECRET)
    r.write("apps/core/src/routing.erl", "route() -> new.\n")
    r.write("env/production.config", SECRET + "_changed\n")
    r.commit(SECRET)
    return r
