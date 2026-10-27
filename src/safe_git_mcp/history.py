import re
from dataclasses import dataclass
from typing import Any

from .backend import Backend
from .config import Policy
from .errors import SafeError
from .models import BlameLine, Change, Commit, Result
from .patches import validate_patch
from .policy import valid_path

SHA = r"(?:[0-9a-f]{40}|[0-9a-f]{64})"


@dataclass(frozen=True)
class Entry:
    path: str
    status: str
    old: str
    new: str


class History:
    def __init__(self, policy: Policy) -> None:
        self.policy = policy
        self.backend = Backend(policy)

    def _result(self, **kwargs: Any) -> Result:
        result = Result(**kwargs)
        if len(result.model_dump_json().encode()) > self.policy.max_response_bytes:
            raise SafeError("OUTPUT_LIMIT")
        return result

    def _path(self, path: str) -> str:
        value = valid_path(path)
        if value is None:
            raise SafeError("INVALID_PATH")
        if not self.policy.allows(value):
            raise SafeError("ACCESS_DENIED")
        return value

    def _number(self, value: int, low: int, high: int) -> None:
        if type(value) is not int or not low <= value <= high:
            raise SafeError("OUTPUT_LIMIT")

    def _meta(self, sha: str) -> tuple[int, list[str]]:
        raw = self.backend._run(["show", "-s", "--format=%H%x00%ct%x00%P", sha]).strip()
        try:
            identity, date, parents = raw.decode("ascii").split("\0")
            parent_list = parents.split()
            if (
                identity != sha
                or not date.isdigit()
                or any(not re.fullmatch(SHA, p) for p in parent_list)
            ):
                raise ValueError
            return int(date), parent_list
        except (UnicodeError, ValueError):
            raise SafeError() from None

    def _entries(self, base: str | None, head: str) -> list[Entry]:
        args = [
            "diff-tree",
            "-r",
            "--no-commit-id",
            "--raw",
            "-z",
            "--no-renames",
            "--no-abbrev",
            "--no-ext-diff",
        ]
        args += [base, head] if base else ["--root", head]
        raw = self.backend._run(args)
        fields = raw.split(b"\0")
        if fields.pop() != b"" or len(fields) % 2:
            raise SafeError()
        if len(fields) // 2 > self.policy.max_changed_files:
            raise SafeError("OUTPUT_LIMIT")
        entries = []
        for i in range(0, len(fields), 2):
            match = re.fullmatch(
                rb":([0-7]{6}) ([0-7]{6}) ([0-9a-f]{40}|[0-9a-f]{64}) "
                rb"([0-9a-f]{40}|[0-9a-f]{64}) ([AMDT])",
                fields[i],
            )
            if not match:
                raise SafeError()
            path = valid_path(fields[i + 1])
            if path is None or not self.policy.allows(path):
                continue
            if any(m not in (b"000000", b"100644", b"100755") for m in (match[1], match[2])):
                continue  # Never expose symlink targets or submodule objects.
            entries.append(Entry(path, match[5].decode(), match[3].decode(), match[4].decode()))
        return entries

    def _blob(self, sha: str) -> bytes:
        if not sha.strip("0"):
            return b""
        size = self.backend._run(["cat-file", "-s", sha], cap=64).strip()
        if not size.isdigit():
            raise SafeError()
        if int(size) > self.policy.max_file_bytes:
            raise SafeError("OUTPUT_LIMIT")
        content = self.backend._run(["cat-file", "blob", sha], cap=self.policy.max_file_bytes)
        if any(token.encode() in content for token in self.policy.quarantine_literals):
            raise SafeError("ACCESS_DENIED")
        return content

    def _files(
        self,
        base: str | None,
        head: str,
        context: int,
        patches: bool = True,
        paths: list[str] | None = None,
    ) -> list[Change]:
        entries = self._entries(base, head)
        files = []
        total = 0
        for entry in entries:
            if paths is not None and entry.path not in paths:
                continue
            patch = ""
            binary = False
            if patches:
                # Blob reads occur only after authorization and enforce per-file limits.
                old, new = self._blob(entry.old), self._blob(entry.new)
                binary = b"\0" in old or b"\0" in new
                if not binary:
                    args = [
                        "diff" if base else "diff-tree",
                        "--no-ext-diff",
                        "--no-textconv",
                        "--no-renames",
                        "--no-color",
                        "--no-relative",
                        "--no-indent-heuristic",
                        "--src-prefix=a/",
                        "--dst-prefix=b/",
                        "--output-indicator-new=+",
                        "--output-indicator-old=-",
                        "--output-indicator-context= ",
                        f"--unified={context}",
                        "--no-commit-id",
                        "-r",
                        "-p",
                    ]
                    args += [base, head] if base else ["--root", head]
                    raw = self.backend._run(
                        [*args, "--", entry.path], cap=self.policy.max_diff_bytes - total
                    )
                    # Attributes can classify a file as binary independently of NUL.
                    if raw.startswith(b"diff --git ") and b"\nBinary files " in raw:
                        binary = True
                    else:
                        patch = validate_patch(raw, entry.path)
                    total += len(raw)
            files.append(
                Change(path=entry.path, change_type=entry.status, patch=patch, binary=binary)
            )
        return files

    def git_log(self, ref: str = "HEAD", limit: int = 20, path: str | None = None) -> Result:
        if path is not None:
            path = self._path(path)
        self._number(limit, 1, self.policy.max_commits)
        with self.backend.operation():
            sha = self.backend.resolve(ref)
            args = ["rev-list", f"--max-count={limit + 1}", sha]
            if path is not None:
                args += ["--", path]
            ids = self.backend._run(args).decode("ascii").splitlines()
            if any(not re.fullmatch(SHA, s) for s in ids):
                raise SafeError()
            commits = []
            for commit in ids[:limit]:
                date, parents = self._meta(commit)
                entries = self._entries(parents[0] if parents else None, commit)
                names = [e.path for e in entries if path is None or e.path == path]
                if names:
                    commits.append(Commit(id=commit, date=date, approved_paths_changed=names))
            return self._result(commits=commits, truncated=len(ids) > limit)

    def git_file_history(self, path: str, ref: str = "HEAD", limit: int = 20) -> Result:
        path = self._path(path)
        result = self.git_log(ref, limit, path)
        return self._result(
            path=path,
            commits=[Commit(id=c.id, date=c.date) for c in result.commits],
            truncated=result.truncated,
        )

    def git_diff(
        self, base: str, head: str, paths: list[str] | None = None, context_lines: int = 3
    ) -> Result:
        self._number(context_lines, 0, self.policy.max_context_lines)
        if paths is not None:
            self._number(len(paths), 1, self.policy.max_changed_files)
            paths = [self._path(p) for p in paths]
        with self.backend.operation():
            b, h = self.backend.resolve(base), self.backend.resolve(head)
            return self._result(base=b, head=h, files=self._files(b, h, context_lines, paths=paths))

    def git_show_commit(self, commit: str, context_lines: int = 3) -> Result:
        self._number(context_lines, 0, self.policy.max_context_lines)
        with self.backend.operation():
            sha = self.backend.resolve(commit)
            _, parents = self._meta(sha)
            if len(parents) > 1:
                raise SafeError("UNSUPPORTED_MERGE")
            return self._result(
                commit=sha,
                parents=parents,
                files=self._files(parents[0] if parents else None, sha, context_lines),
            )

    def git_changed_files(self, base: str, head: str) -> Result:
        with self.backend.operation():
            b, h = self.backend.resolve(base), self.backend.resolve(head)
            return self._result(base=b, head=h, files=self._files(b, h, 0, patches=False))

    def git_blame(
        self, path: str, ref: str = "HEAD", start_line: int = 1, end_line: int = 100
    ) -> Result:
        path = self._path(path)
        self._number(start_line, 1, 1000000)
        self._number(end_line, start_line, min(1000000, start_line + 499))
        with self.backend.operation():
            sha = self.backend.resolve(ref)
            raw = self.backend._run(["ls-tree", "-z", sha, "--", path])
            match = re.fullmatch(
                rb"(100644|100755) blob (" + SHA.encode() + rb")\t(.*)\0", raw, flags=re.DOTALL
            )
            if not match or match[3] != path.encode():
                raise SafeError("ACCESS_DENIED")
            content = self._blob(match[2].decode())
            if b"\0" in content:
                raise SafeError("ACCESS_DENIED")
            raw = self.backend._run(
                [
                    "blame",
                    "--line-porcelain",
                    "--no-progress",
                    "-L",
                    f"{start_line},{end_line}",
                    sha,
                    "--",
                    path,
                ]
            )
            lines = []
            identity: tuple[str, int] | None = None
            for line in raw.split(b"\n"):
                header = re.fullmatch(rb"(" + SHA.encode() + rb") \d+ (\d+)(?: \d+)?", line)
                if header:
                    if identity is not None:
                        raise SafeError()
                    identity = (header[1].decode(), int(header[2]))
                elif line.startswith(b"\t"):
                    if identity is None or not start_line <= identity[1] <= end_line:
                        raise SafeError()
                    try:
                        text = line[1:].decode("utf-8", "strict")
                    except UnicodeError:
                        raise SafeError() from None
                    lines.append(BlameLine(line_no=identity[1], commit=identity[0], text=text))
                    identity = None
            if identity or len(lines) != end_line - start_line + 1:
                raise SafeError()
            return self._result(path=path, lines=lines)
