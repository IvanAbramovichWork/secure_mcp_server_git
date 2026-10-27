# Validation record

Validated locally on Linux, Python 3.12.14, Git 2.52.0, MCP SDK 2.3.0.
All Git fixtures are temporary synthetic repositories; ECSS10 was not inspected.

Commands and observed results:

- `UV_CACHE_DIR=/tmp/safe-git-uv-cache uv sync --locked --group dev`: succeeded.
- `.venv/bin/pytest -q --tb=short`: **105 passed**, no skips or expected failures.
- `.venv/bin/ruff check .`: passed.
- `.venv/bin/ruff format --check .`: 26 files already formatted.
- `.venv/bin/mypy src`: no issues in 12 source files (strict mode).
- `UV_CACHE_DIR=/tmp/safe-git-uv-cache uv build`: wheel and source distribution built.

Development followed test-first cycles: policy tests (35 initial failures),
backend/ref tests (22 initial failures), history tests (18 initial failures),
stdio tool tests (8 initial failures), then implementation and passing reruns.
Optional content quarantine and complete-response limits had failing tests before
implementation. Additional coverage checks exercised existing behavior.

A fresh read-only security review found three defects. Each received a reproduced
failing regression, a correction and a full-suite passing rerun:

1. Promisor/lazy-fetch configuration could invoke a remote upload-pack helper on
   missing blobs. Remote config is now restricted, lazy fetching disabled, and Git
   protocols prohibited. The synthetic helper marker remains absent.
2. Malformed TOML strings/tables could become tuples instead of being rejected.
   All four list fields now require TOML arrays, verified by eight negative cases.
3. Compact application JSON did not include duplicated MCP text/structured output.
   The guard now caps serialized tool results after SDK conversion. The stdio
   regression observed 1267 bytes against a 1000-byte cap before the fix and now
   returns a safe OUTPUT_LIMIT.

A child CPU-limit regression failed with unlimited rlimits, then passed after
adding Linux prlimit. Timeout tests verify descendant process-group termination.
Other coverage includes root/merge/empty/mixed commits; malformed refs and paths;
branch/tag ambiguity; annotated tags and detached HEAD; protected historical
sentinels; whitespace/newline/Unicode/invalid UTF-8 filenames; binary and deleted
files; symlinks/gitlinks; attributes/external diff/textconv; inherited Git env;
config/root integrity; alternates/replace refs; corrupt output and generic errors;
working-tree independence; byte/file/call/time limits; MCP schemas and all six
tools through the official stdio client. Intentional residual-risk tests show
allowed-content and protected-to-allowed rename exposure, with optional literal
quarantine tested separately.

Not run: other Python/Git versions (CI matrix is configured), Claude Code
registration/red-team prompts, any separately approved external test repository,
production data, a privileged authenticated broker, or OS/UID/mount/network
isolation tests. No hardened-deployment acceptance or publication is claimed.
