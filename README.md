# Safe Git MCP

A standalone, read-only, policy-filtered Git history server for Linux, using the
**official MCP Python SDK v2** (`mcp==2.3.0` in `uv.lock`). This is a local stdio
prototype. It minimizes Git data returned by this API; it does not isolate an
agent from files accessible through other tools or processes.

## Additional project denies

A project can add restrictions through the standard `.mcp.json` registration `env`:

```json
"env": {
  "SAFE_GIT_PROJECT_DENY_PATHS": "[\"internal/**\", \"notes/private/**\"]"
}
```

The mandatory operator policy remains enforced. Project denies also override
operator allow exceptions, apply to every tool and cannot change the repository
or limits. Malformed rules refuse startup. The [project-denies guide](docs/PROJECT_DENIES.md)
has complete native and Compose `.mcp.json` examples, direct Docker forwarding,
limits and trust caveats. Rebuild the image and reconnect after updating.

## Compose deployment

Use the shared `compose.yaml` with a per-project env file. Copy `.env.example` to
an operator-managed location, fill PROJECT_ROOT/POLICY_FILE and HOST_UID/HOST_GID,
and keep the Docker TOML policy binding at `/repo`:

```sh
docker compose --file compose.yaml --env-file /absolute/path/project-a.env build safe-git
docker compose --file compose.yaml --env-file /absolute/path/project-a.env \
  run --rm --no-deps -T safe-git doctor --policy /policy/policy.toml
```

The [Compose guide](docs/COMPOSE.md) includes safe file creation, complete Claude
registration and several-project examples. No host Python installation is needed.
Environment files supply interpolation only; unrelated variables are not injected
into the service. Runtime restrictions are centralized in Compose. Existing
linked-worktree and whole-agent-isolation limitations apply.

## Docker deployment

Docker packages Python, Git, util-linux and the locked application dependencies:

```sh
docker build -t safe-git-mcp:local .
```

Use the [Docker guide](docs/DOCKER.md) for the external `/repo` policy, read-only
mounts, UID matching, preflight checks and `eltex-claude` registration. Runtime
networking is disabled and no ports are exposed. Linked worktrees remain
unsupported. This contains the server; it does not isolate a host-side agent or
implement the separate privileged broker.

## Easier local deployment

After cloning (or `git pull --ff-only` in an existing installation):

```sh
uv sync --locked
.venv/bin/safe-git-mcp setup --name project-a \
  --repo /absolute/path/to/approved-standalone-test-repo \
  --client eltex-claude --register
eltex-claude mcp list
```

`setup` expands CLI `~` paths, generates an absolute binding and full default
policy at `~/.config/safe-git-mcp/project-a.toml` with private file permissions,
checks prerequisites/repository initialization, and tests a real MCP stdio
handshake before registration. The default client is `eltex-claude`; use
`--client claude` for standard Claude Code. Omit `--register` to print the exact
registration command without modifying client settings. Review the generated
policy before using confidential data. Local mode still requires separate OS
isolation for strong confidentiality.

Repeat setup with another `--name` and `--repo` for each independent repository.
Existing policies are preserved, including reviewed rules. A different binding or
invalid existing policy is a conflict, never overwritten. Setup never removes
existing client registrations; a duplicate registration may require operator
review in the client. `--config-dir` selects another operator-managed directory.

Diagnose an existing installation without pasting configuration or Git output:

```sh
.venv/bin/safe-git-mcp doctor --policy ~/.config/safe-git-mcp/policy.toml
```

Doctor returns a static reason code such as `POLICY_INVALID`, `PRLIMIT_MISSING`,
`LINKED_WORKTREE_UNSUPPORTED`, `REPOSITORY_REJECTED` or `MCP_CONNECTION_FAILED`.
It reads trusted startup metadata and does a handshake/list-tools request; it
never retrieves file patches. A successful result does not prove the deployed
client's permissions or OS isolation. Setup/doctor are operator commands, never
MCP tools or agent-controlled repository selection.

**Linked worktrees remain unsupported.** They are identified without opening the
`.git` pointer or following it to original history. Setup will not silently bind
a main checkout or weaken checks. Use an explicitly approved independent test
repository; never edit the pointer to bypass this restriction.

## Development

Requires Python 3.11+, Git (validated on 2.52.0), uv, and Linux util-linux
`/usr/bin/prlimit`. The implementation uses
Linux/POSIX process groups and selectors. Git must support `rev-parse
--end-of-options`. Use the existing isolated cloud checkout; no extra worktree is
needed. From this repository:

```sh
UV_CACHE_DIR=/tmp/safe-git-uv-cache uv sync --locked --group dev
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy src
```

Tests create temporary synthetic Git repositories with distinctive fake secrets.
No ECSS10 checkout, production history, network access, or credentials are used by
the server or test suite. Dependencies require package-registry access to install.
The specification is preserved in [docs/SPEC.md](docs/SPEC.md).

## Run

Copy `config/policy.example.toml` to an operator-managed location, set
`repository_root` to a separately approved test repository, review the policy,
then run:

```sh
.venv/bin/python -m safe_git_mcp --policy /absolute/operator-owned/policy.toml
```

Stdout is MCP-only. Stderr contains fixed tool names and outcome codes. The server
refuses missing/malformed policy and unsafe repository layouts/configuration.
There is no default repository and no repository parameter in the tools.
The policy is loaded once; stop and restart to apply policy changes. Live
processes must be restarted after cloud environment restoration.

## Tools

| Tool | Inputs | Returned data |
|---|---|---|
| `git_log` | `ref="HEAD", limit=20, path=null` | Approved commit IDs, timestamps, approved changed paths |
| `git_file_history` | `path, ref="HEAD", limit=20` | IDs/timestamps for the literal path, no rename following |
| `git_diff` | `base, head, paths=null, context_lines=3` | Approved regular-file patches between two commits |
| `git_show_commit` | `commit, context_lines=3` | Approved root/single-parent commit patches and parent IDs |
| `git_changed_files` | `base, head` | Approved regular-file names/status, no content |
| `git_blame` | `path, ref="HEAD", start_line=1, end_line=100` | At most 500 approved historical lines with commit IDs |

Responses are typed structured objects. Unused fields are empty/null. Failures
have `error.code`, a generic message and MCP `isError=true`. Codes include
`ACCESS_DENIED`, `INVALID_REF`, `INVALID_PATH`, `INVALID_INPUT`, `OUTPUT_LIMIT`,
`TIMEOUT`, `UNSUPPORTED_MERGE`, `INTERNAL_ERROR`. No raw Git errors are returned.

Refs accept HEAD, full 40/64-character object IDs resolving to commits, ASCII
branch/tag names, and explicit `refs/heads/...` or `refs/tags/...`. Annotated tags
are peeled without returning annotations. Ambiguous branch/tag names fail.
Revision expressions (`HEAD~1`, `REV:PATH`, ranges, options) are rejected; obtain
parent hashes from `git_show_commit` instead.

Root commits use `diff-tree --root`. Merge patch requests fail with
`UNSUPPORTED_MERGE`; `git_log` lists approved first-parent changes. Explicit
two-commit `git_diff` comparisons can include merge endpoints. Log/history scan
at most `limit` commits and omit entries with no approved changes: fewer than
`limit` results is normal. `truncated=true` means further candidate history
exists; there is no pagination token. Empty histories do not fabricate commits.

Names are UTF-8, case-sensitive Git paths. `*`/`?` match within a component; a
whole `**` component matches zero or more components. Patterns are root anchored,
without gitignore negation or bracket classes. Root `*.pem` is denied by
`**/*.pem`; `apps/sorm*/**` also denies `apps/sorm_adapter/...`. Invalid UTF-8,
absolute paths, NUL, dot traversal, empty components, backslashes, `.git`
components and option/pathspec-looking prefixes fail closed. Invalid names in
Git enumeration are discarded; valid whitespace/newline/Unicode names are
handled literally. Symlinks, gitlinks and type transitions involving them are
omitted, never dereferenced. Non-UTF-8 patches fail; binary patches are omitted
with `binary=true` and empty `patch`.

## Limits and troubleshooting

The sample policy limits commits, enumerated changed files (including denied
entries), approved blob size, aggregate patch bytes, serialized MCP tool-response bytes, elapsed
request time, per-child CPU rlimits, and subprocess count. Stdout/stderr share a bounded capture budget;
request subprocesses share one deadline and byte/call budget. Overflows fail
closed rather than returning partial data. Tight limits can make a mixed commit
unavailable; reduce the query or have an administrator review limits. Both text/structured result copies and JSON overhead count toward response limits.
Fixed generic failure envelopes are exempt from tiny configured response limits;
JSON-RPC framing/request IDs and schema-list responses are outside this tool-data cap. A blame range must fit the file.

Only ordinary non-bare checkouts with an owned `.git` directory are supported.
Linked worktrees, bare repositories, shallow clones, grafts and alternates are
rejected. Config changes or checkout-directory replacement require restart.
Global/system Git config and inherited `GIT_*` environment are ignored. Unknown
local config keys, includes and unsupported extensions cause startup failure.
Supported local groups are basic core keys, benign remote URL/fetch/tag settings,
branch, user, diff and filter;
promisor/helper remote settings are rejected, lazy fetching is disabled and
Git protocols are denied. No remote commands execute, and external diff/textconv/filter helpers are never
invoked. Paths used to launch this server and its environment must be trusted.

Commit messages, author names/emails, tag annotations, notes and reflogs are never
returned. Approved filenames, content, object IDs, timestamps, parent IDs, result
sizes and timings still reveal information. Files moved/copied from protected
paths into approved paths remain a **residual leak**. The optional exact-substring
`quarantine_literals` check rejects content-bearing responses on matches, but
cannot classify all secrets or prove provenance. Metadata-only tools do not run
content detectors. See [SECURITY.md](SECURITY.md), [deployment](docs/DEPLOYMENT.md),
[Claude setup](docs/CLAUDE_SETUP.md), and the separate
[production hardening plan](docs/HARDENED_DEPLOYMENT.md).
