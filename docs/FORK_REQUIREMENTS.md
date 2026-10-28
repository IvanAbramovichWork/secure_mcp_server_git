# Requirements: upstream-based Safe Git MCP

Date: 2026-10-28. Status: requirements draft for implementation planning.

## 1. Goal and decisions

Build a new Git MCP server from a genuine fork of
[`modelcontextprotocol/servers`](https://github.com/modelcontextprotocol/servers),
extending `src/git`. Preserve every supported feature, security control,
deployment option and documented limitation of the current Safe Git MCP server.
Add upstream Git functionality through the same authorization layer, including
**operator-enabled writes**. The default remains read-only.

The user explicitly selected a fork and opted into support for separately enabled
write capabilities. The tool naming, capability layout and rollout below are
proposed implementation choices, not previously approved interface details.
This document specifies the target; it does not claim the fork or features exist.

Requirements use MUST for release gates, SHOULD for recommendations and MAY for
optional enhancements. All mandatory requirements apply to native and container
launches unless a mode is explicitly identified.

### Source baselines

| Source | Pinned revision | Purpose |
|---|---|---|
| Upstream servers | `ef9808f71090d0db3eda99e2af2ba78f1086f4fb` | Fork ancestry and upstream tool behavior |
| Current Safe Git MCP | `eac23ff71c6b5ede2ea2957062f893a6c1c9ad8e` | Compatibility, policy and regression baseline |

Pinned references:

- [Upstream Git implementation](https://github.com/modelcontextprotocol/servers/blob/ef9808f71090d0db3eda99e2af2ba78f1086f4fb/src/git/src/mcp_server_git/server.py)
- [Upstream package](https://github.com/modelcontextprotocol/servers/blob/ef9808f71090d0db3eda99e2af2ba78f1086f4fb/src/git/pyproject.toml)
- [Current implementation](https://github.com/IvanAbramovichWork/secure_mcp_server_git/tree/eac23ff71c6b5ede2ea2957062f893a6c1c9ad8e)
- [Original supplied specification](SPEC.md), [threat model](THREAT_MODEL.md),
  [security limitations](../SECURITY.md), [validation history](VALIDATION.md)

The current implementation and explicit decisions in this document govern
compatibility where the original specification describes an unimplemented future
mode. Preserve the distinction between implemented behavior and planned hardening.

## 2. Fork, architecture and maintenance

- **FORK-01:** Preserve upstream Git history and attribution, configure an
  `upstream` remote, and record the base revision and downstream changes. Do not
  rewrite the existing Safe Git repository or delete its working release.
- **FORK-02:** Keep changes focused on `src/git`, its tests, packaging, deployment
  assets and necessary CI. Unrelated MCP servers MUST remain unchanged.
- **FORK-03:** Preserve applicable upstream license files, notices and authorship.
  The pinned root LICENSE describes an MIT/Apache-2.0 transition and documentation
  licensing, while the Git package declares MIT; do not replace this with an
  assumption that all files have one license. Record applicable notices before
  distributing the fork.
- **FORK-04:** Use upstream MCP registration/lifecycle as the starting point and
  integrate the existing policy, restricted Git execution, result models and
  deployment helpers as shared components. No upstream handler may bypass them.
  GitPython may remain only where its execution and output can satisfy these
  requirements; dependency reuse does not justify unrestricted Git calls.
- **FORK-05:** Keep official MCP Python SDK v2 support, Python 3.11+ and Linux
  support. Lock dependencies and build reproducible wheel, sdist and image
  artifacts. Clearly distinguish the downstream distribution from upstream.
- **FORK-06:** Preserve `safe-git-mcp`, `python -m safe_git_mcp`, `--policy`, and
  operator `setup`/`doctor` entry points through compatibility adapters. Retain
  `Policy.load` and `SafeError` imports used by existing diagnostic instructions.
- **FORK-07:** Document upstream synchronization. Every update requires review of
  new tools, changed schemas, Git execution, exception handling and logging, plus
  rerunning downstream security tests. New upstream tools MUST NOT automatically
  become exposed or authorized.

Approaches considered: extending the standalone implementation would preserve
its small surface but would not meet the request for an upstream fork. A wrapper
that filters upstream text cannot prevent protected content from being read.
The selected approach is a real fork with a shared policy/execution layer before
content access, retaining compatibility adapters for current clients.

## 3. Tool inventory and compatibility

### Existing tools: mandatory compatibility surface

**API-01:** Preserve these exact names, arguments, defaults, structured result
fields and documented semantics. Do not silently substitute upstream semantics.

| Tool | Existing arguments | Required behavior |
|---|---|---|
| `git_log` | `ref="HEAD", limit=20, path=null` | IDs, commit timestamps and approved changed paths; no messages or identities |
| `git_file_history` | `path, ref="HEAD", limit=20` | Literal-path history; no rename following |
| `git_diff` | `base, head, paths=null, context_lines=3` | Compare two committed revisions; never implicitly compare a working tree |
| `git_show_commit` | `commit, context_lines=3` | Root/single-parent approved patches and parent IDs; merge patch request returns `UNSUPPORTED_MERGE` |
| `git_changed_files` | `base, head` | Approved paths and change types without patches |
| `git_blame` | `path, ref="HEAD", start_line=1, end_line=100` | Inclusive one-based lines, at most 500; line number, commit ID and text |

**API-02:** Keep the current `Result` envelope (`error`, `commits`, `files`,
`lines`, `base`, `head`, `commit`, `parents`, `path`, `truncated`), with unused
fields empty/null. Preserve MCP structured content, its JSON text representation
and `isError` behavior. New tools may define separately versioned typed results.

**API-03:** Preserve log/history candidate-scan limits, omission of commits with
no approved changes, and `truncated` semantics. Merge log paths use first-parent
changes. Explicit two-commit diffs may use merge endpoints. Root commits work;
empty history returns no fabricated entries. No existing pagination is implied.

### Upstream features to integrate

**API-04:** Provide the following additional operations. Names below deliberately
resolve the upstream/current `git_diff` conflict. All returned paths, content and
metadata pass the same policy as existing tools.

| Upstream tool | Downstream interface | Required adaptation |
|---|---|---|
| `git_status` | `git_status` | Structured approved staged/unstaged/untracked path statuses; no raw porcelain output or protected names |
| `git_diff_unstaged` | Same name | Approved index-to-working-tree patches for tracked regular files |
| `git_diff_staged` | Same name | Approved HEAD-to-index patches; support an unborn HEAD |
| `git_diff(target)` | `git_diff_worktree(target, paths=null, context_lines=3)` | Approved commit-to-working-tree patches; preserve existing two-commit `git_diff` |
| `git_log` | Existing `git_log` | Preserve existing schema; provide upstream-style date filtering through a separate `git_log_filtered` tool with bounded ISO-8601 start/end inputs |
| `git_show` | `git_show(revision, context_lines=3)` | Commit-only alias of `git_show_commit`; reject tree/blob and `REV:PATH` reads; retain the merge restriction |
| `git_branch` | `git_branch(branch_type="local", contains=null, not_contains=null)` | Bounded local/remote/all branch names and target IDs; validate filter refs; no remote URLs, fetches or commit subjects |
| `git_add` | Same name | Stage only explicitly named, authorized literal files/deletions |
| `git_reset` | Same name | Unstage all only when every affected staged change is authorized; no hard reset or file deletion |
| `git_commit` | Same name | Commit the authorized staged change set only; hooks/signing disabled |
| `git_create_branch` | Same name | Create an authorized new local branch at a validated commit; no overwrite |
| `git_checkout` | Same name | Switch only under the checkout requirements below; no force, merge or discard behavior |

**API-05:** Define bounded, strict schemas and structured outputs for additions
before implementing handlers. `git_log_filtered` MUST reuse current safe log
output, default ref/limit and candidate-budget semantics; upstream author/message
text is not a compatibility requirement. Reject unknown arguments and wrong
types without echoing values. None of these tools accepts `repo_path`, executable
paths, environment overrides, policy rules or arbitrary Git options.

**API-06:** The new server is not a drop-in replacement for upstream's unrestricted
schemas or human-readable responses. Document renamed operations, omitted raw
blob/tree access and constrained revision syntax. Branch names are a new metadata
disclosure: document that path denies do not classify ref names, and permit an
operator to disable branch enumeration entirely.

## 4. Mandatory policy and data protection

- **POL-01:** Require a strict, immutable operator TOML policy and one absolute,
  fixed repository binding per server process. Missing, unreadable, malformed or
  unknown policy settings fail closed. No repository auto-discovery from the MCP
  caller's directory, nested repository selection or fallback to unrestricted
  upstream behavior.
- **POL-02:** Preserve denylist and allowlist modes, exact-path operator allow
  exceptions, default deny patterns, and optional literal quarantine. Preserve
  every current setting and default in `config/policy.example.toml`.
- **POL-03:** Preserve case-sensitive, root-anchored component glob semantics:
  `*`/`?` do not cross `/`; whole-component `**` matches zero or more components.
  Do not reinterpret these as regex or gitignore rules. Preserve UTF-8 literal
  path handling and rejection of traversal, absolute paths, NUL, backslashes,
  `.git` components and option/pathspec-looking prefixes.
- **POL-04:** Enumerate names and modes before reading content. Authorize each
  path before reading blobs, working-tree bytes, patches or blame. For changes
  with two path endpoints, authorize both; metadata-only responses also suppress
  protected names. Broad read operations omit denied entries; explicit denied
  path arguments return `ACCESS_DENIED`. Writes involving any unauthorized
  affected path reject the entire operation before mutation.
- **POL-05:** Preserve startup-only `SAFE_GIT_PROJECT_DENY_PATHS` as a JSON array
  string in standard `.mcp.json` `env`, native execution, direct Docker forwarding
  and Compose interpolation. These restrictions intersect operator authorization
  after allow exceptions, append to operator `project_deny_paths`, and cannot
  change the binding, grant writes or increase limits.
- **POL-06:** Preserve project input limits: 65,536 UTF-8 bytes; at most 128
  combined project patterns; at most 256 characters/32 components per pattern.
  Malformed JSON/types/globs and explicit empty values reject startup. Unset
  means no additional rules; `[]` is valid. Rules remain frozen until restart.
- **POL-07:** Never return commit messages, author names/emails, tag annotations,
  notes, reflogs, remote URLs or raw repository configuration. Existing
  `return_commit_messages` and `return_author_identity` remain false-only.
  An accepted write message is input for the commit, not permission to disclose
  it through any read response or log.
- **POL-08:** Preserve omission of symlinks, gitlinks and transitions involving
  them. Never dereference symlinks/submodules for content. Binary patches have
  `binary=true` and empty patch; invalid UTF-8 patches fail safely. Disable
  rename/copy detection, validate patch framing, and apply quarantine before
  releasing approved content. Metadata-only operations do not read content just
  to run quarantine.
- **POL-09:** Accept only current constrained refs: HEAD, full SHA-1/SHA-256 commit
  IDs and validated ASCII branch/tag names, including explicit heads/tags refs.
  Peel annotated tags without exposing annotations. Reject ambiguous short refs,
  options, ranges, ancestry expressions and `REV:PATH`. Resolve accepted refs to
  concrete IDs within a request.

## 5. Write authorization and side effects

**WRITE-01 — Explicit opt-in.** Add an operator-only capability section, disabled
by default, with independent grants for stage, unstage, commit, create-branch and
checkout. Exact TOML spelling is a builder decision, documented before coding.
Project files, environment variables, tool arguments and Docker writability MUST
NOT enable capabilities. Disabled tools MUST be absent from `tools/list` and
reject direct calls without executing Git or touching the repository.

**WRITE-02 — Additional scope.** Require a nonempty operator write-path allowlist
for stage/unstage/commit/checkout and an operator local-branch-name allowlist for
create-branch/branch checkout. Tag checkout requires a separate operator tag-name
allowlist; detached commit checkout requires its own grant. Effective write access
is the intersection of the normal path decision, project denies and the write
allowlist. Operator read exceptions cannot bypass project denies or write scope.
Local-branch rules cannot target tags,
remote refs or internal `.git` paths. No capability grants push, fetch, pull,
clone, arbitrary reset, merge, rebase, clean or generic command execution.

**WRITE-03 — Known repository state.** Before every write, validate HEAD, index,
affected paths/modes and repository integrity. Reject merge/rebase/cherry-pick/
revert/bisect states and unmerged index entries. Hold a service-level exclusive
mutation lock with a bounded wait; integrate safely with Git lock files. Verify
expected state immediately before mutation. The service must have exclusive
custody of a write-enabled checkout; concurrent external writers are unsupported
and detected changes fail closed. Do not claim race safety against same-UID
malicious filesystem mutation.

**WRITE-04 — Staging.** `git_add` accepts a bounded nonempty array of literal file
paths. Reject directory expansion, `.`/`-A`, globs, pathspec magic, symlink/gitlink
entries and unsafe ancestors. Authorize each path and inspect size/mode before
reading bytes. Support explicit authorized deletions. Stage raw content without
executing clean filters, Git LFS helpers or other repository-defined programs.
Preflight the full batch before changing the index; validation failure leaves it
unchanged. Do not invoke upstream's unrestricted add handler behind a precheck.

**WRITE-05 — Unstaging.** Preserve upstream's unstage-all operation only if its
complete affected set is authorized. If even one protected or out-of-write-scope
path would be reset, reject the whole call. Working-tree files remain untouched.
Handle an unborn HEAD explicitly and return structured affected paths only.

**WRITE-06 — Commit.** Check the complete staged delta, including changes staged
outside this server; never merely trust paths from an earlier `git_add`. Reject
unauthorized changes, mode transitions, conflicts and quarantined changed content
before creating a commit. Unchanged protected tree entries may be inherited from
the parent without reading their content. Empty commits and merge commits are
out of scope. Commit identity comes from operator-controlled settings, never
caller arguments. A bounded UTF-8 message is accepted but never echoed. Return
the new ID and approved changed paths, not identities, message or Git stdout.

**WRITE-07 — Branch creation.** Validate branch syntax and operator branch scope;
resolve a constrained base commit; create only a new local branch. Never force
overwrite, change remote configuration or check out the branch implicitly.

**WRITE-08 — Checkout.** Preserve upstream branch/tag/commit checkout, subject to
explicit operator scope: a local branch or tag must match its separate allowlist;
detached commit checkout requires its own grant. Require a globally clean index
(compare names/modes/object IDs without opening denied blobs). Compute the complete
source-to-target tree delta before mutation and require the affected tracked
working-tree paths to be clean. Every changed source and destination path must be
readable and writable under policy. Reject protected changes, untracked
collisions, in-progress operations, symlinks/gitlinks, unsafe ancestors and
out-of-budget trees. Paths outside that delta, including dirty protected files,
must remain untouched; do not read their content to establish global cleanliness.
Reject the switch if the implementation cannot prove these conditions without
prohibited reads. Never force, discard changes, recurse into submodules or
implicitly create branches. No-op switches need not read protected content.
Use no external checkout filters.

**WRITE-09 — No executable side effects.** Disable repository/global hooks,
signing, editors, askpass, credential helpers, pagers, external diffs, textconv,
clean/smudge/process filters, fsmonitor and protocol helpers for all operations.
Inventory every newly reachable Git config/attribute execution path. If a Git
operation cannot safely disable required transformations, reject that layout or
implement the operation through reviewed lower-level commands. Tests must prove
that marker-producing synthetic helpers never execute.

**WRITE-10 — Bounded and honest outcomes.** Bound input files, aggregate write
bytes, message bytes, index/tree enumeration, subprocesses, CPU, elapsed time and
response size. Commit-message default cap: 4,096 UTF-8 bytes; default aggregate
staging cap: 1 MiB; existing per-file/file-count limits also apply. Operators may
lower these limits; any increased bounds need explicit documented maxima.
Reserve the bounded success/error response envelope before mutation so that an
output-limit check cannot turn an already completed write into an ordinary
preflight rejection. Preflight rejection makes no persistent change.
After mutation begins, timeout,
cancellation or I/O failure may leave state changed: return a generic
`WRITE_STATE_UNCERTAIN`, stop further writes in that process and require operator
inspection/restart. Never claim rollback without verifying it, or blindly retry
commit/checkout. Successful responses identify the resulting commit/branch where
safe. Read-only calls must never mutate Git state.

## 6. Git execution, limits, transport and audit

- **EXEC-01:** Fixed executable and explicit argv, `shell=False`, fixed repository
  and Git directory, literal path handling and a cleaned environment. Ignore
  inherited `GIT_*`, global/system config and credentials. Deny protocols and
  lazy fetching. No network access or credential requirement at runtime.
- **EXEC-02:** Preserve ownership/config/layout integrity checks and rejection of
  unsupported local config, includes, helpers, replacement objects, grafts,
  alternates, shallow/bare repositories and linked worktrees. Keep safe handling
  of benign current config groups without executing their helpers. Writable
  objects/refs must not weaken read-mode layout checks without a documented
  replacement and regression tests.
- **EXEC-03:** Preserve shared per-request deadlines, byte/call budgets, bounded
  combined stdout/stderr capture, process-group termination and Linux
  `/usr/bin/prlimit` child CPU limits. Apply them to GitPython too if retained.
  No uncapped preliminary command or helper is exempt.
- **EXEC-04:** Preserve default read limits: 100 commits, 500 enumerated changed
  files including denied entries, 256 KiB diff, 128 KiB file, 1 MiB complete tool
  response, 10 context lines, eight seconds and 2,048 subprocesses. Maintain
  current supported configuration ranges and aggregate accounting semantics.
- **EXEC-05:** Fail closed on resource overflow without partial read data. Count
  both text/structured copies and JSON overhead. Preserve the documented small
  fixed-error exemption; JSON-RPC framing/request IDs and tool schemas are outside
  the tool-data cap. New branch/status enumeration also needs bounded candidate
  counts, charging denied entries before filtering.
- **EXEC-06:** Local stdio is the required transport: stdout MCP-only, no runtime
  ports/listener. Preserve sanitized stable codes including `ACCESS_DENIED`,
  `INVALID_REF`, `INVALID_PATH`, `INVALID_INPUT`, `OUTPUT_LIMIT`, `TIMEOUT`,
  `UNSUPPORTED_MERGE`, `INTERNAL_ERROR`; document new capability/write codes.
- **EXEC-07:** Suppress raw SDK/GitPython/Git exception output and validation
  echoes. Audit only bounded fixed tool/outcome/capability identifiers on stderr;
  never arguments, filenames, refs, messages, identities, content, environment,
  configuration values or tracebacks. Unknown tool names must not enter logs.
- **EXEC-08:** Working-tree/index read tools must discover candidate names/modes
  without diffing or opening denied contents, then inspect only approved paths.
  Do not assume an unrestricted `git status` or name-only diff avoids content
  reads. Use beneath-root, no-symlink traversal for filesystem reads, reject
  unsafe ancestors, and detect inconsistent snapshots rather than mixing index,
  HEAD and working-tree states. Disable optional Git locks/index refresh writes
  during read requests, for example through `GIT_OPTIONAL_LOCKS=0`; prove that
  status/diff/branch enumeration leaves refs, index and repository files unchanged.

## 7. Deployment and operator experience

- **DEP-01:** Preserve native setup/doctor behavior, per-project 0600 policies,
  CLI tilde expansion, absolute TOML binding, exclusive creation, no overwrite of
  reviewed policies, conflict diagnostics, real SDK initialize/list-tools checks,
  quoted registration previews and argv-only `eltex-claude`/`claude` registration.
  Client output remains suppressed; failed registration does not delete policy.
- **DEP-02:** Preserve project-root `.mcp.json` registration through standard
  command/args/env fields. Do not read arbitrary custom policy fields from it.
  Doctor uses the effective additive denies, forwards only the dedicated startup
  variable, reads no patches and never tests writes. Setup never persists optional
  environment-derived denies into operator TOML. It must not enable writes without
  explicit operator configuration.
- **DEP-03:** Preserve separate processes/policies for independent project dirs,
  with no cross-project selection or leakage. Linked `.git` files remain
  unsupported; diagnose without opening/following the pointer. Worktree support
  requires a separately reviewed design and is not part of feature preservation.
- **DEP-04:** Preserve the Docker build-context allowlist, pinned base/dependencies,
  no baked-in policies/credentials/repositories, non-root matching UID:GID,
  network none, dropped capabilities, no-new-privileges, read-only root, limited
  CPU/memory/PIDs, private noexec/nosuid tmpfs and cleared proxy variables.
  Preserve recursive read-only/rprivate repository mounts in the default mode,
  read-only policy mounts and fail-closed missing bind sources.
- **DEP-05:** Preserve Compose `.env` interpolation for `PROJECT_ROOT`,
  `POLICY_FILE`, `HOST_UID`, `HOST_GID`, image selection and optional project
  denies. Do not inject the complete env file. Ignore private env files in Git;
  track only the root example. Document shell-over-dotenv precedence, literal
  quoting, spaces, explicit-empty failure and no source/eval usage.
- **DEP-06:** Provide a separate explicit write deployment configuration with
  only the approved repository and necessary Git metadata writable. Keep root,
  policy and executable read-only and all other runtime restrictions. A writable
  mount alone must leave write tools disabled. Doctor must detect a requested
  write capability with an unwritable deployment without performing a write.
  Never weaken the default Compose service to accommodate write mode.
- **DEP-07:** Provide complete native/Docker/Compose `.mcp.json` examples, multiple
  independent-project examples, setup troubleshooting, write enable/disable and
  recovery instructions. Preserve direct Docker explicit variable forwarding and
  Compose's dedicated mapping. No image registry publication is implied.

## 8. Test-first acceptance criteria

**TEST-01:** Use TDD: first failing policy/security and compatibility tests, then
the restricted backend, then tool handlers and deployment integration. Every
feature or bug fix must demonstrate a meaningful failing test before its code.
Use only temporary synthetic repositories and distinctive fake secrets. Never
inspect, modify, mount or run tests against the real ECSS10 repository/history.

**TEST-02:** Port all current regression behaviors (180 tests at the pinned
baseline, including opt-in Docker/Compose tests). Adapt harness details where
necessary but do not remove a protection to accommodate upstream. Keep upstream
tests where semantics remain compatible; document changed/replaced assertions.
Test count alone is not acceptance evidence.

| Acceptance group | Required evidence |
|---|---|
| Existing six tools | Official SDK stdio calls; unchanged schemas/defaults/envelopes; equivalent approved results |
| Every new read/write tool | Operator and project denies; explicit-denied-input rejection; no sentinel in results, errors or logs |
| Authorization before content | Denied corrupt/missing blobs and instrumented working-tree readers prove no denied-content reads; filtering text afterward fails this test |
| Ref/path handling | Ambiguity, annotated tags, detached HEAD, root/merge/empty commits, malicious options/pathspecs, traversal, Unicode/newline/invalid UTF-8 names |
| Content modes | Binary/deleted files, symlinks, gitlinks, mode transitions, rename/copy residuals, quarantine and exact exceptions |
| Default read-only | Write tools absent; forged calls rejected; before/after refs/index/files/object-store state unchanged |
| Capability isolation | Each capability alone; no environment/project escalation; read exception does not grant write scope |
| Staging/unstaging | Multi-file batch with one denied path rejects atomically; protected pre-staged data; unborn HEAD; literal deletions; no whole-directory expansion |
| Commit | Authorized staged set succeeds; externally staged denied entry rejects; no identity/message output; no empty/merge commit; timeout-after-mutation uncertainty |
| Branch/checkout | Separate branch/tag scopes, existing-name collision, detached grant, dirty affected files/index, untouched dirty protected files, conflicts, untracked collision, protected target delta, unsafe ancestor, no forced overwrite |
| Execution safety | Marker hooks/filters/signing/fsmonitor/helpers never run; poisoned config/environment, lazy fetching and alternate layouts reject |
| Concurrency/failure | Parallel writes serialized; changed expected state rejects; lock timeout; process descendants killed; uncertain writes block further mutation |
| Budgets | Byte/file/candidate/message/write/time/CPU/call limits, duplicated MCP output, sanitized errors without partial data |
| Deployment | Setup/doctor races and policy preservation; native env, direct Docker, Compose, spaces and two concurrent isolated projects |
| Real container modes | Inspect runtime restrictions; default write attempts fail; explicit write mount plus grant succeeds only within allowed paths; no network/socket/credentials |

**TEST-03:** Run lint, formatting, strict typing, package builds and a documented
Python/Git CI matrix. Separate native, read-only image/Compose and write image/
Compose jobs. Release evidence must identify commands, versions, revisions,
results and untested environments. Actual client registration is a distinct
claim from official SDK transport tests. Security review must resolve important
findings before write mode is released.

## 9. Boundaries and explicit limitations

- This API does not confine a same-UID agent using shell, filesystem tools or
  another MCP route. Docker confines the server, not a host-side agent. Access
  to the Docker socket is not a safe agent permission.
- Project-writable `.mcp.json` can replace the command or mounts. Mandatory
  policy, launch configuration and executable must be operator-managed for
  stronger claims. Optional denies can be removed; mandatory ones belong in TOML.
- Path policy does not classify secrets in approved content or detect protected
  files copied/renamed into approved paths. Keep residual-leak tests and explain
  literal quarantine's limited role. Returned repository text is untrusted data,
  including possible prompt injection.
- Approved names, branch names, hashes, timestamps, parent IDs, sizes and timing
  remain metadata disclosure. No general provenance, redaction or noninterference
  guarantee is implied.
- Immutable snapshots are recommended for read-only deployments. Write mode
  necessarily changes that assumption and requires an exclusively managed
  writable checkout; it cannot inherit immutable-snapshot assurances.
- Authenticated brokers, separate service identities, whole-agent confinement,
  Windows/macOS native support, remote Git operations, linked worktrees, bare/
  shallow repositories and arbitrary blob/tree reads are outside this release.
  Preserve the separate [hardening plan](HARDENED_DEPLOYMENT.md) without presenting
  it as implemented.

## 10. Delivery and migration gates

1. **Requirements and provenance:** review this document, create the remote fork
   without changing the existing repository, record its URL/base and retain
   notices. Remote creation currently has no completion evidence: GitHub API
   account access returned `Forbidden` during requirements preparation.
2. **Compatibility first:** port policy, execution and six-tool regression tests;
   integrate the shared enforcement layer; pass the unchanged read-only contract.
3. **Upstream read features:** implement the adapted read interfaces, structured
   schemas and all security tests. No raw upstream handler remains reachable.
4. **Write capabilities:** implement staged grants and preflight behavior, tests
   for each mutation and uncertain outcome, plus independent security review.
5. **Deployment parity:** retain native and default read-only Docker/Compose
   behavior; add separate explicit write deployment and migration examples.
6. **Release:** pass all applicable checks, produce artifacts and migration notes,
   and verify the actual MCP tool inventory in each capability mode. Keep the
   existing release available; no automatic policy rewrite or client replacement.

The requirements document is the current deliverable. Product implementation,
distribution/remote repository naming and publication are subsequent steps.
Builders may choose internal module layout, supported-library internals and
fixture organization while meeting the public contracts and release gates above.
