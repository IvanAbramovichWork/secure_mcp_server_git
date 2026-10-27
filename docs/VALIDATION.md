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

## Deployment helper update — 2026-10-27

Added operator-only `setup`/`doctor` commands. Initial CLI tests produced nine
expected failures before implementation; four invalid-name cases already failed
closed under the old parser. Setup now creates per-project absolute policies,
preserves existing rules, previews or executes argv-only client registration,
and runs a real official-client stdio handshake. Doctor identifies invalid policy,
missing prerequisites and unsupported worktrees without following Git pointers.

Fresh review found a policy-creation race; two tests reproduced new-file and
symlink insertion during preflight (RED), then passed after retaining the original
create/reuse decision and enforcing exclusive creation (GREEN). A missing-prlimit
test initially patched os.access too broadly and masked Git availability; its
fixture was narrowed to the prlimit path. No unresolved test failures remain.

Final commands/results on the same local Python/Git versions:

- `.venv/bin/pytest -q --tb=short`: **127 passed**, no skips or expected failures.
- `.venv/bin/ruff check .`: passed.
- `.venv/bin/ruff format --check .`: 30 files already formatted.
- `.venv/bin/mypy src`: no issues in 13 source files.
- `UV_CACHE_DIR=/tmp/safe-git-uv-cache uv build`: wheel and source distribution built.

Tests cover synthetic setup, preserved/conflicting/malformed policies, tilde
expansion, file permissions, unsupported worktree diagnostics, safe registration
argv including spaces, suppressed client output, retained policies on client
failure, missing prerequisites, policy symlinks, concurrent creation and sanitized
handshake errors. Client registration is tested with a synthetic executable;
actual `eltex-claude`/Claude Code installation is not available here. Successful
helper registration means client CLI exit success; verify effective client state
with `eltex-claude mcp list`. Production/ECSS10, linked-worktree support, and OS
isolation remain outside this update. No real ECSS10 repository was accessed.

## Docker deployment update — 2026-10-27

Built and exercised a real Linux amd64 Docker image using Engine 28.4.0. The
container has Python 3.12.16 and Git 2.39.5. Official Python multi-platform base
manifest is pinned to sha256:6dd8b6dab6b3adc7812bab69eca5dbdc1a5cc690ad28306d234ffb4ef8ac9753;
local tested image ID is sha256:61679e68c71b952a8c31ddc864648298ba312a708141ae470533190af1577d2e.

Three initial Docker tests failed before the image existed, then passed after
building. Two further real-image checks verify default UID:GID 10001:10001 and
successful `doctor` readiness. Review added fail-closed recursive read-only binds
with explicit rprivate propagation and documented Docker/kernel prerequisites.

Cloud build containers initially could not resolve package servers. The successful
build used the platform's existing proxy, a build-only trusted CA secret and
build-network routing. APT's downloader required the CA mount to be readable by
its unprivileged identity; the public CA bundle is mounted mode 0444, never copied
to the runtime. TLS, package signature and artifact verification stayed enabled.

A full-suite run exposed Docker-client automatic proxy injection: 131 passed and
one runtime-environment assertion failed. Image inspection confirmed proxy keys
were absent from image configuration. The documented/tested runtime now explicitly
clears upper/lowercase HTTP_PROXY, HTTPS_PROXY, ALL_PROXY and NO_PROXY values. The
regression passed, followed by the complete successful run below.

Final verification:

- Real Docker image build succeeded with the environment's proxy/CA configuration.
- `SAFE_GIT_DOCKER_TESTS=1 .venv/bin/pytest -q --tb=short`: **132 passed**, no skips.
- `.venv/bin/ruff check .`: passed.
- `.venv/bin/ruff format --check .`: 33 files already formatted.
- `.venv/bin/mypy src`: no issues in 13 source files.
- `UV_CACHE_DIR=/tmp/safe-git-uv-cache uv build`: wheel and source distribution built.

Container tests use generated fake-secret repositories and the official SDK stdio
client. They verify filtered responses, protected-path denial, runtime write
failures, zero effective capabilities, no-new-privileges, no network route,
non-root UID matching, absence of Docker socket/build CA/temporary CA config,
cleared runtime proxy values, no runtime source checkout, and safe rejection of
an unmounted linked-worktree pointer. CI has a separate image-build/Docker-test
job; default native pytest marks the five Docker tests skipped unless opted in.
No ECSS10 access occurred. No ARM runtime, actual eltex-claude registration,
registry image publication, authenticated broker or whole-agent isolation was
validated or claimed. Existing linked-worktree and provenance limits remain.
