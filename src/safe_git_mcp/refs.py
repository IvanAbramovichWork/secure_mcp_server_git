import re

from .errors import SafeError


def candidates(ref: str) -> list[str]:
    if not isinstance(ref, str) or not 1 <= len(ref) <= 256:
        raise SafeError("INVALID_REF")
    if ref == "HEAD" or re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", ref):
        return [ref]
    if (
        not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_./-]*", ref)
        or ".." in ref
        or any(
            p in ("", ".", "..") or p.endswith((".", ".lock")) or p.startswith(".")
            for p in ref.split("/")
        )
    ):
        raise SafeError("INVALID_REF")
    if ref.startswith(("refs/heads/", "refs/tags/")):
        return [ref]
    if ref.startswith("refs/"):
        raise SafeError("INVALID_REF")
    return ["refs/heads/" + ref, "refs/tags/" + ref]
