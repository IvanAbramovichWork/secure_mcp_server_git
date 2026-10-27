"""Private fixed-argv Git execution. No caller-controlled command or environment."""

import contextlib
import math
import os
import re
import selectors
import shutil
import signal
import subprocess
import threading
import time
from collections.abc import Iterator
from pathlib import Path

from .config import Policy
from .errors import SafeError


class Budget:
    def __init__(self, seconds: float, size: int, calls: int) -> None:
        self.deadline = time.monotonic() + seconds
        self.remaining = size
        self.calls = calls


def capture(
    argv: list[str], cwd: Path, env: dict[str, str], budget: Budget, cap: int | None = None
) -> bytes:
    budget.calls -= 1
    if budget.calls < 0:
        raise SafeError("OUTPUT_LIMIT")
    if time.monotonic() >= budget.deadline:
        raise SafeError("TIMEOUT")
    out = bytearray()
    size = 0
    limit = min(budget.remaining, cap if cap is not None else budget.remaining)
    try:
        cpu = max(1, math.ceil(budget.deadline - time.monotonic()))
        limited_argv = ["/usr/bin/prlimit", f"--cpu={cpu}:{cpu + 1}", "--", *argv]
        with subprocess.Popen(
            limited_argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            start_new_session=True,
        ) as process:
            assert process.stdout is not None and process.stderr is not None
            try:
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ, True)
                    selector.register(process.stderr, selectors.EVENT_READ, False)
                    while selector.get_map():
                        remaining = budget.deadline - time.monotonic()
                        if remaining <= 0:
                            raise SafeError("TIMEOUT")
                        for key, _ in selector.select(min(remaining, 0.05)):
                            chunk = os.read(key.fd, 65536)
                            if not chunk:
                                selector.unregister(key.fileobj)
                                continue
                            size += len(chunk)
                            if size > limit:
                                raise SafeError("OUTPUT_LIMIT")
                            if key.data:
                                out.extend(chunk)
                    process.wait(timeout=max(0.001, budget.deadline - time.monotonic()))
                if process.returncode in (-signal.SIGXCPU, -signal.SIGKILL):
                    raise SafeError("TIMEOUT")
                if process.returncode:
                    raise SafeError()
            finally:
                # Kill descendants even if the original process has already exited.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
    except SafeError:
        raise
    except subprocess.TimeoutExpired:
        raise SafeError("TIMEOUT") from None
    except Exception:
        raise SafeError() from None
    budget.remaining -= size
    return bytes(out)


class Backend:
    def __init__(self, policy: Policy) -> None:
        self.policy = policy
        self.lock = threading.RLock()
        self.root = policy.repository_root.resolve(strict=True)
        self.gitdir = self.root / ".git"
        self.executable = shutil.which("git", path="/usr/bin:/bin") or "/usr/bin/git"
        self.env = {
            "PATH": "/usr/bin:/bin",
            "HOME": "/nonexistent",
            "LANG": "C",
            "LC_ALL": "C",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_PROTOCOL_FROM_USER": "0",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_PAGER": "cat",
            "GIT_ATTR_NOSYSTEM": "1",
        }
        try:
            if (
                not self.gitdir.is_dir()
                or self.gitdir.is_symlink()
                or self.root.stat().st_uid != os.geteuid()
                or self.gitdir.stat().st_uid != os.geteuid()
            ):
                raise SafeError()
            self.identity = self._identity()
            self.config = self._config_bytes()
            self.budget = self._budget()
            raw = capture(
                [
                    self.executable,
                    "config",
                    "--file",
                    str(self.gitdir / "config"),
                    "--no-includes",
                    "--null",
                    "--list",
                ],
                self.root,
                self.env,
                self.budget,
            )
            for item in raw.split(b"\0"):
                if not item:
                    continue
                key = item.split(b"\n", 1)[0].decode("ascii").lower()
                safe_core = {
                    "core.repositoryformatversion",
                    "core.filemode",
                    "core.bare",
                    "core.logallrefupdates",
                    "core.ignorecase",
                    "core.precomposeunicode",
                    "core.quotepath",
                    "core.autocrlf",
                    "core.eol",
                }
                if key not in safe_core and not (
                    key.startswith(("branch.", "user.", "diff.", "filter."))
                    or re.fullmatch(r"remote\..+\.(url|fetch|pushurl|tagopt)", key)
                ):
                    raise SafeError()
            if self._run(["rev-parse", "--show-toplevel"]).strip() != os.fsencode(self.root):
                raise SafeError()
            if self._run(["for-each-ref", "--format=%(refname)", "refs/replace"]).strip():
                raise SafeError()
        except Exception:
            raise SafeError() from None

    def _identity(self) -> tuple[int, ...]:
        return (
            self.root.stat().st_dev,
            self.root.stat().st_ino,
            self.gitdir.stat().st_dev,
            self.gitdir.stat().st_ino,
        )

    def _config_bytes(self) -> bytes:
        config = self.gitdir / "config"
        if config.is_symlink() or config.stat().st_size > 65536:
            raise SafeError()
        return config.read_bytes()

    def _check(self) -> None:
        try:
            if self.gitdir.is_symlink() or self._identity() != self.identity:
                raise SafeError()
            if self._config_bytes() != self.config:
                raise SafeError()
            for rel in (
                "objects/info/alternates",
                "objects/info/http-alternates",
                "info/grafts",
                "shallow",
                "commondir",
            ):
                if os.path.lexists(self.gitdir / rel):
                    raise SafeError()
            for rel in ("objects", "refs"):
                if (self.gitdir / rel).is_symlink():
                    raise SafeError()
        except Exception:
            raise SafeError() from None

    def _budget(self) -> Budget:
        return Budget(
            self.policy.max_runtime_seconds,
            1048576 + 4 * self.policy.max_diff_bytes,
            self.policy.max_subprocesses,
        )

    @contextlib.contextmanager
    def operation(self) -> Iterator[None]:
        with self.lock:
            self.budget = self._budget()
            self._check()
            yield

    def _run(self, args: list[str], cap: int | None = None) -> bytes:
        self._check()
        return capture(
            [
                self.executable,
                "--no-pager",
                "--literal-pathspecs",
                "--git-dir=" + str(self.gitdir),
                "--work-tree=" + str(self.root),
                "-c",
                "protocol.allow=never",
                "-c",
                "protocol.file.allow=never",
                "-c",
                "protocol.ext.allow=never",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "core.attributesFile=/dev/null",
                "-c",
                "core.quotePath=true",
                "-c",
                "diff.renames=false",
                "-c",
                "diff.algorithm=myers",
                "-c",
                "color.ui=false",
                *args,
            ],
            self.root,
            self.env,
            self.budget,
            cap,
        )

    def resolve(self, ref: str) -> str:
        from .refs import candidates

        values = candidates(ref)
        found: list[str] = []
        for value in values:
            try:
                sha = (
                    self._run(["rev-parse", "--verify", "--end-of-options", value + "^{commit}"])
                    .strip()
                    .decode("ascii")
                )
            except SafeError as exc:
                if exc.code != "INTERNAL_ERROR":
                    raise
                continue
            if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", sha):
                raise SafeError()
            found.append(sha)
        if len(found) != 1:
            raise SafeError("INVALID_REF")
        return found[0]
