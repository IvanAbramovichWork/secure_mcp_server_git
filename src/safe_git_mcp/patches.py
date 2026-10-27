"""Validate single-file Git diff framing before returning any patch bytes."""

import re

from .errors import SafeError


def quoted(path: str) -> bytes:
    raw = path.encode("utf-8")
    if all(32 <= c < 127 and c not in (34, 92) for c in raw):
        return raw
    escapes = {
        7: b"\\a",
        8: b"\\b",
        9: b"\\t",
        10: b"\\n",
        11: b"\\v",
        12: b"\\f",
        13: b"\\r",
        34: b'\\"',
        92: b"\\\\",
    }
    return (
        b'"'
        + b"".join(
            escapes.get(c, bytes([c]) if 32 <= c < 127 else f"\\{c:03o}".encode()) for c in raw
        )
        + b'"'
    )


def validate_patch(raw: bytes, path: str) -> str:
    if not raw:
        return ""
    lines = raw.split(b"\n")
    if lines.pop() != b"":
        raise SafeError()
    a, b = quoted("a/" + path), quoted("b/" + path)
    if lines.pop(0) != b"diff --git " + a + b" " + b:
        raise SafeError()
    old = new = 0
    hunk = False
    for line in lines:
        match = re.fullmatch(rb"@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@.*", line)
        if match:
            if old or new:
                raise SafeError()
            old = int(match[1]) if match[1] is not None else 1
            new = int(match[2]) if match[2] is not None else 1
            hunk = True
        elif hunk:
            if line.startswith(b" "):
                old -= 1
                new -= 1
            elif line.startswith(b"-"):
                old -= 1
            elif line.startswith(b"+"):
                new -= 1
            elif line != b"\\ No newline at end of file":
                raise SafeError()
            if old < 0 or new < 0:
                raise SafeError()
        elif line.startswith(b"--- "):
            if line[4:].rstrip(b"\t") not in (a, b"/dev/null"):
                raise SafeError()
        elif line.startswith(b"+++ "):
            if line[4:].rstrip(b"\t") not in (b, b"/dev/null"):
                raise SafeError()
        elif not re.fullmatch(
            rb"(?:index [0-9a-f]+\.\.[0-9a-f]+(?: [0-7]{6})?"
            rb"|(?:old mode|new mode|new file mode|deleted file mode) [0-7]{6})",
            line,
        ):
            raise SafeError()
    if old or new:
        raise SafeError()
    try:
        return raw.decode("utf-8", "strict")
    except UnicodeError:
        raise SafeError() from None
