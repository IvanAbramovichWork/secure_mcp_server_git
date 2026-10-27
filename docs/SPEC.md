# Safe Git MCP Server — Implementation Specification

**Status:** Implementation-ready specification (Codex handoff)  
**Date:** 2026-10-26  
**Target:** ECSS10, local Git repository and Claude Code on Linux  
**Recommended language:** Python 3.11+  
**MCP SDK:** Official Python MCP SDK v2 (`mcp>=2,<3`, pinned with a lockfile)  
**Transport:** Local MCP `stdio` initially; authenticated service transport only if a separate privilege boundary is required

> **Security principle:** Do not use `.gitattributes`, natural-language instructions, hooks, or regex-only redaction as a security boundary. The server must *construct responses exclusively from explicitly approved Git data*. The Claude-side process must not have another route to forbidden working-tree files or original Git objects. Until that latter condition is met, this is a **data-minimizing Git API**, not a hard confidentiality boundary.

## 0. Assignment to Codex

Build a **read-only, policy-enforcing Git MCP server** in a **new standalone repository**. Do not modify ECSS10 or its history. Implement the functionality and tests described below, beginning with synthetic Git fixtures containing *fake* secrets. Do not use real credentials, real ECSS10 protected files, or production Git history in tests. Do not claim security guarantees without running the listed negative tests. Favor deny-by-default behavior over convenience; document limitations and unresolved cases.

**Deliverables**

1. Executable MCP server with typed tool interfaces and stdio transport.
2. Fixed repository binding, central path policy, and secure Git subprocess layer.
3. `git_log`, `git_diff`, `git_show_commit`, `git_file_history` (MVP); `git_blame` and `git_changed_files` after MVP.
4. Structured, bounded, filtered responses; no raw Git stderr/stdout in client-facing errors.
5. Unit, integration, and adversarial tests using generated Git repositories.
6. Developer README, deployment README, sample policy, example Claude Code configuration, and security limitations document.
7. CI commands: lint, type checking, unit/integration tests; dependency lockfile.
8. A **separate** production-hardening plan for full OS isolation / privilege-separated broker. Do not conflate local stdio mode with hardened isolation.

## 1. Problem and security goals

ECSS10 contains valuable Erlang source-code history alongside confidential applications, deployment configurations, certificates, cookies, MCP settings, and potentially historical credentials. Claude Code needs to inspect **allowed** changes and commit timelines, but must not receive the contents of protected historical files.

### In scope

- Reading approved historical file diffs, commit IDs/dates, and filtered changed-file lists.
- Filtering every tool output using one centralized policy.
- Preventing arbitrary `git show REV:PATH`, `git cat-file`, `--text`, `--binary`, `-c`, `--ext-diff`, external textconv, and raw shell argument pass-through **through this MCP interface**.
- Malformed input, empty or root commits, merge commits, unusual filenames, symlinks, renames, tags, detached HEAD, very large history, Git errors.
- Deployment alongside Claude Code's Bash sandbox with Git object access denied to sandboxed commands.
- Clear guidance on the stronger, separate-user or containerized production deployment.

### Out of scope for v1

- Git write operations (`commit`, `checkout`, `add`, `reset`, `push`, `fetch`, `pull`, `merge`, etc.).
- Generic Git CLI proxy or arbitrary Git flags/refspecs.
- Working-tree status or uncommitted diffs from a *different* agent workspace. The trusted history server is bound to a fixed original repository; agent checkout status, if needed, must be implemented as a separate validated workspace-specific feature, not inferred from the original repo.
- Guaranteed identification of secrets in *allowed* code or in git metadata.
- Automatically trusting repository-supplied hooks, filters, attributes, or scripts.
- Promising that a same-UID local MCP process and Bash-only sandbox completely isolate confidential data.

### Threat model

Assume Claude may issue any permitted MCP arguments, generate arbitrary Bash/Python/Erlang code, request unsupported revisions, specify malicious paths/options, and use other configured tools. Also assume repository contents and commit messages can contain prompt injection. Distinguish accidental mistakes from a deliberately adversarial agent. The trusted server is responsible for outputs **it** produces; a complete guarantee requires a separate OS-enforced boundary protecting the original repository from **all other** agent execution paths.

## 2. Architecture and trust boundaries

### Mode A — Local prototype (no hard OS guarantee)

```text
Claude Code (same Linux UID as developer)
  |-- Bash sandbox: denyRead original .git and protected paths
  |-- Read/Grep/Edit: separate Claude permissions; NOT covered by Bash sandbox
  |-- other MCPs/hooks: outside Bash sandbox; must be audited
  `-- safe-git MCP server (stdio; outside Bash sandbox)
         |-- policy engine
         |-- validated Git read-only operations
         `-- original ECSS10 repository
```

This mode is suitable for development/testing **only**. Claude Code permissions and sandboxing reduce risk, but the same UID ordinarily retains access outside Bash sandbox boundaries. Do not describe this as strong confinement.

### Mode B — Hardened deployment (target for confidential data)

```text
Agent container / restricted UID / separate mount namespace
  |-- Approved workspace (source files with protected paths absent)
  |-- No mount/read permission for original ECSS10 or original Git objects
  |-- No developer SSH credentials / GitLab original-repo access
  `-- MCP bridge (unprivileged client)
            | authenticated local socket / protected HTTP transport
            v
      Trusted Safe Git service (separate privilege domain)
            |-- policy validation and audit
            |-- immutable ECSS10 repository binding
            `-- read-only access to original Git history
```

**Critical:** A stdio MCP child launched by Claude Code inherits its UID and filesystem environment. A *privileged* service must not be implemented by simply launching stdio code as the same agent UID. For hardened mode, run the Git service under a separate restricted service identity (or outside the agent container), connect through an authenticated bridge, and prohibit any other agent access to the repository. Socket access must be authorization-scoped and the server must be read-only.

The agent workspace also needs to exclude protected files in the **current working tree**, not merely hide `.git` objects. It is acceptable for plain `git log` to fail in the agent workspace: the agent must use MCP Git tools for history access.

## 3. Policy: source of truth

Use a **server-owned** policy file that the agent cannot modify. The server's `repository_root` is configured at startup and is never accepted as an MCP tool argument.

Proposed TOML format (new format to implement, not native to Git):

```toml
repository_root = "/home/ivan.abramovich/ecss10"
policy_mode = "denylist" # v1; support "allowlist" in hardening phase
max_commits = 100
max_changed_files = 500
max_diff_bytes = 262144
max_file_bytes = 131072
max_context_lines = 10
max_runtime_seconds = 8
return_commit_messages = false
return_author_identity = false

# Git paths are repository-relative, POSIX-separated and case-sensitive.
# Apply to every version of a path, not just HEAD.
deny_paths = [
  "env/**",
  "root/etc/ecss/**",
  "apps/sorm*/**",
  "apps/lpm*/**",
  "apps/ecss_storekeeper/config/**",
  "_deps/ecss_license_agent/**",
  "**/*.pem",
  "**/*.secret.exs",
  "**/.env",
  "**/.env.*",
  "**/.erlang.cookie",
  "**/.erlang.crypt",
  ".mcp.json",
  "**/settings.local.json",
  ".claude/**"
]

# Optional after review; override only exact safe templates, e.g. .env.example.
allow_exceptions = []
```

**Policy implementation requirements:**

- Define a single `is_allowed_git_path(path: bytes | str)` function, tested independently of Git.
- Normalize only **Git path syntax**, not filesystem paths; reject absolute paths, NUL bytes, `..` path components, empty components where invalid, and ambiguous encodings. For Git's arbitrary byte filenames, fail closed if they cannot be represented under the chosen API encoding.
- Test patterns in root and nested directories. Ensure `*.pem` and nested `.env` cases match as intended. **Do not assume Python `fnmatch` or `pathlib` exactly matches Git `.gitattributes`/gitignore syntax.** Define and test one explicit matching semantics, including `**` and `apps/sorm*/**`.
- A default-deny **allowlist** of permitted `apps/core/**`, `apps/mediator/**`, etc. is preferred for a stricter later deployment; newly added paths then stay unavailable until reviewed.
- Preserve access-control policy in a root-owned/admin-managed file in hardened mode. If the agent can edit the policy or server executable, protection fails.
- A file previously containing confidential data that is later **renamed or copied to an allowed path** cannot be deemed safe by path filtering alone. Require a content/provenance review, allowlist approval, or an explicit quarantine policy for those cases.
- Treat **filenames, commit messages, author identities, and patches** as potentially confidential. Omit commit messages/author email in secure defaults. Later exposure must be separately reviewed and documented.

## 4. Proposed MCP tools

All responses should be typed JSON objects (structured tool output), not raw concatenated Git stdout. Use stable error codes (`ACCESS_DENIED`, `INVALID_REF`, `INVALID_PATH`, `OUTPUT_LIMIT`, `TIMEOUT`, `UNSUPPORTED_MERGE`, `INTERNAL_ERROR`) and generic error messages. Don't include unsanitized path, Git stderr, or raw exception text in error objects.

| Tool | Request | Response (illustrative) | Notes |
|---|---|---|---|
| `git_log` | `ref="HEAD", limit=20, path=null` | `{commits:[{id,date,approved_paths_changed}]}` | Validate optional path first; omit raw messages by default. |
| `git_diff` | `base, head, paths=null, context_lines=3` | `{base,head,files:[{path,change_type,patch}],truncated}` | Compare **two commits** only in v1, not arbitrary worktrees. |
| `git_show_commit` | `commit, context_lines=3` | `{commit,parents,files:[...],truncated}` | No `REV:PATH` grammar accepted. Merge patch handling explicitly defined. |
| `git_file_history` | `path, ref="HEAD",limit=20` | `{path,commits:[{id,date}]}` | Reject protected paths before invoking Git. |
| `git_changed_files` | `base,head` | `{files:[{path,change_type}]}` | Only approved names; optional after MVP. |
| `git_blame` | `path,ref="HEAD",start_line,end_line` | `{path,lines:[{line_no,commit,text}]}` | Only approved historical file content; no unsafe raw porcelain metadata. Phase 2. |

No `repo_path` parameter, no shell command string, no arbitrary Git options, no checkout/add/commit tools, no direct `cat-file` MCP operation, no Git remotes supplied by callers.

**Example:**

Request `git_show_commit({"commit":"HEAD"})` resolves HEAD to a commit and returns only diffs for approved files. A change to `apps/core/src/ivr_block_queue_fsm.erl` may appear; a change to `apps/sorm/config.xml` must not appear at all (not even in the file list). The result should indicate `redacted_files_present: true` only if revealing the *existence* of hidden paths is explicitly allowed by policy; default false/omitted.

## 5. Secure data construction algorithm

### A. Resolve refs

- Accept only a constrained revision grammar: `HEAD`, exact branch/tag names that pass a parser, or object IDs. **Never** interpolate user-supplied values into a shell command.
- Resolve each requested revision to a concrete *commit SHA* with a fixed argv invocation and `git rev-parse --verify --end-of-options ...^{commit}` (confirm compatibility on supported Git versions); reject other object types. Consider using an explicit `refs/heads/` / `refs/tags/` lookup to avoid ambiguous revisions.
- Use only resolved hashes for subsequent Git commands. Explicitly cap input lengths and reject option-looking values beginning with `-`.
- Resolve repository root and Git directory at startup from trusted configuration; reject repository changes or unexpected Git alternates. No user-selected repository.

### B. Obtain changed paths first (never expose raw output)

- Run an internal name/status enumeration with `-z` NUL delimiters and rename/copy detection **disabled**, or use a Git library that yields structured name/status records.
- Parse byte filenames, validate every path, apply `is_allowed_git_path`, and discard protected entries **before** requesting patches or line content.
- Treat changes crossing a protected-to-allowed rename/copy boundary conservatively. **Do not claim that `--no-renames` detects such transitions:** use a separate, internally parsed rename/copy provenance check if implementing quarantine. Until proven, flag this as a residual risk; an allowed destination path can contain previously protected content.
- Bound the number of files; on overflow either return an explicit safe `OUTPUT_LIMIT` error or a clearly marked approved-only prefix with deterministic pagination. MVP may fail closed.

### C. Generate patches only for approved paths

- For each approved path, invoke Git with **fixed arguments** and literal path selection (`--literal-pathspecs` or an equivalent verified literal pathspec form), after the `--` separator.
- Disable rename/copy detection, external diff drivers, textconv, color, paging, and word-diff; never emit `--binary` patches or accept `--text` from clients.
- Use bounded unified-context lines (`0..10`) and bounded output bytes per request.
- For root commits, compare against the empty tree or explicitly handle `--root`.
- For merge commits, v1 either **return metadata only and `UNSUPPORTED_MERGE` for patch requests** or explicitly diff against the first parent and label the semantics. Do not accidentally expose a combined diff with unvetted paths.
- Never pass unvalidated diff output directly to an MCP response: verify the diff file boundaries/headers against the permitted path and run optional secret-scanning on allowed patches. If structure is unexpected, **return a generic error rather than unfiltered output**.

### D. Commit metadata

- Do **not** return raw `git log`/`git show` output. Build the response from explicitly requested safe fields (`%H`, commit timestamp, parent IDs). Commit subjects and bodies are **omitted by default** because they may embed secrets or sensitive paths.
- If later allowing commit messages, require a separately defined metadata disclosure policy. Regex detectors alone are not an assurance.
- Keep Git tree, tag annotation, notes and reflog text out of the API unless explicitly audited.

### E. Secure Git process execution

- Use `subprocess` with `shell=False`, an argv list, fixed working directory, timeout, output-size cap, and cleaned environment. No calls to `os.system`, `shell=True`, arbitrary user command or string concatenation.
- Clear inherited `GIT_*` variables except deliberately constructed safe ones; disable prompts, global/system config overrides and Git external helpers wherever possible. Fix pager behavior and disallow external diff/textconv.
- Audit repository-local Git config, replace objects, alternates, custom attributes, and supported Git versions. Read-only commands should never invoke repository-supplied hooks, but **verify all subprocess execution paths** rather than assuming.
- Run with minimum privileges, no Git credentials, no network requirement, and no remote-fetch tools. Validate configured repository ownership and avoid `safe.directory=*`.
- Capture stdout/stderr privately; never return raw stderr or an exception containing raw Git output. Scrub logs; write structured events without file contents.
- Use hard per-operation limits for CPU time, subprocess count, output bytes and number of paths; terminate child process groups on timeout.
- On any parser, Git, policy, or transport error, emit a generic structured failure; do not send partial unvalidated output.

## 6. Implementation modules and structure

```text
safe-git-mcp/
├── pyproject.toml
├── uv.lock
├── README.md
├── SECURITY.md
├── config/
│   └── policy.example.toml
├── src/safe_git_mcp/
│   ├── __init__.py
│   ├── __main__.py         # start stdio server
│   ├── server.py           # MCP SDK v2 tool registration
│   ├── config.py           # validated policy loading
│   ├── policy.py           # Git path matching and authorization
│   ├── refs.py             # Git revision resolution
│   ├── backend.py          # restricted Git subprocess wrapper
│   ├── history.py          # approved commits/patch construction
│   ├── models.py           # typed request/response schemas
│   ├── errors.py           # generic client errors
│   └── audit.py            # metadata-only security events
├── tests/
│   ├── conftest.py         # creates temporary Git fixture repos
│   ├── test_policy.py
│   ├── test_refs.py
│   ├── test_history.py
│   ├── test_security.py
│   └── test_mcp_integration.py
└── docs/
    ├── THREAT_MODEL.md
    ├── CLAUDE_SETUP.md
    └── HARDENED_DEPLOYMENT.md
```

Use the official **MCP Python SDK v2** API (`from mcp.server import MCPServer`, `@mcp.tool()`, stdio `mcp.run()`) after verifying current released behavior. The reference `mcp-server-git` may inform architecture but currently uses SDK v1; do not blindly import v1 classes into a v2 project.

## 7. Prototype Claude Code integration

Register the implemented server through a trusted, user-scoped command (illustrative path, after implementation):

```bash
claude mcp add --transport stdio --scope user safe-git -- \
  /home/ivan.abramovich/safe-git-mcp/.venv/bin/python \
  -m safe_git_mcp \
  --policy /home/ivan.abramovich/.config/safe-git-mcp/policy.toml

claude mcp list
# Inside Claude Code: /mcp
```

Do **not** put this security-critical policy under a repository-controlled `.mcp.json` or writable project tree. Do not allow the agent to edit the server executable or policy.

**Illustrative Claude sandbox settings** (merge into real settings; check effective configuration in `/sandbox`):

```json
{
  "sandbox": {
    "enabled": true,
    "failIfUnavailable": true,
    "allowUnsandboxedCommands": false,
    "filesystem": {
      "denyRead": [
        "/home/ivan.abramovich/ecss10/.git",
        "/home/ivan.abramovich/ecss10_ai_security/.git",
        "/home/ivan.abramovich/ecss10/env",
        "/home/ivan.abramovich/ecss10/root/etc/ecss"
      ]
    }
  },
  "permissions": {
    "deny": [
      "Read(/home/ivan.abramovich/ecss10/.git/**)",
      "Read(/home/ivan.abramovich/ecss10_ai_security/.git)",
      "Read(/home/ivan.abramovich/ecss10/env/**)"
    ]
  }
}
```

**This JSON is not a complete final security policy.** The deployment guide must derive and cover **all** protected working-tree paths, the real Git common directory (`git rev-parse --path-format=absolute --git-common-dir`), the worktree `.git` pointer, alternates, and any other sensitive directories. `denyRead` covers sandboxed Bash and children; built-in file tools, hooks, MCP servers, LSPs and some shell paths remain outside the Bash sandbox. Confirm that no direct host, remote, credential, Unix socket or additional MCP route can retrieve original Git objects. Apply managed settings or whole-process isolation if the policy must be enforced independently of the agent's settings.

### Stronger deployment work item (not MVP)

- A service identity (e.g. `gitreader`) or host-side broker with read-only access to the original repo.
- Agent under separate UID/container, with approved source workspace and **no** access to original repository or Git object store (including mounts, `objects/info/alternates`, symlinks, GitLab remote, credentials).
- Authenticated Unix socket / protected HTTP transport, with client allowlist; a small unprivileged MCP bridge connects Claude to broker.
- Broker's request schema and path policy identical to v1 MCP tools; no arbitrary Git command proxy.
- No Docker socket, SSH agent, broad privileged Unix sockets, raw GitLab MCP connector, or arbitrary `sudo` in the agent environment.
- Host-managed code/policy inaccessible for writes to agent; audit and test negative access under actual agent identity.

## 8. Required security test matrix

Create Git fixtures with distinctive **fake sentinel secrets** in both historical and current protected paths (e.g. `ECSS10_TEST_SECRET_DO_NOT_EXPOSE_12345`) and assert the marker never appears in **any** MCP response, exception, tool description, debug log, or error produced by the tests. Also put a fake secret into an *allowed* file to show that path policies alone do not protect secrets in allowed content; document this residual risk, then add optional detector/quarantine behavior.

At minimum cover:

| Case | Expected result |
|---|---|
| Allowed `apps/core/src/routing.erl` change | Patch returned |
| Protected `env/production.config` change | No name, diff or content returned |
| Same commit changes allowed and forbidden files | Only allowed changes returned |
| `apps/sorm/src/x.erl` and `apps/sorm_adapter/...` | Both forbidden |
| Nested `.env`, `.env.local`, `.erlang.cookie`, `*.pem` | Forbidden |
| Root commit | Safe handling; filtered first commit |
| Merge commit | Documented safe behavior (deny patch or first-parent) |
| `git_file_history` for forbidden path | `ACCESS_DENIED` |
| Revision string `HEAD:env/production.config` | `INVALID_REF` |
| Revision `--all`, `-p`, `-c`, option injection | Rejected |
| Relative path `../env/...`, absolute path, NUL, `:(glob)` | Rejected |
| Filename with whitespace/newlines/Unicode | Correct parse or fail closed |
| Filenames with invalid UTF-8 | Fail closed |
| Rename/copy from forbidden to allowed path | If detected, quarantine / reject; otherwise document as a residual risk and never claim this is solved by `--no-renames` |
| Symlink and submodule entries | No dereferencing of forbidden/host paths |
| Commit subject includes sentinel secret | Subject not returned in default mode |
| Git stderr includes sentinel secret | Only generic error exposed |
| Overlong diff, too many files, timeout | Safe bounded error |
| Missing policy, unreadable policy, corrupted Git output | Deny or refuse startup, never fall back |
| Different repo passed by caller | Impossible (no caller repository parameter) |
| Raw Git option, Git config override or shell string | Impossible (not in schema) |
| Git attributes define external diff/textconv | External commands not executed |
| Working tree changes after start | Doesn't let caller select new repo |
| Policy file modified by agent | Fails deployment hardening test; in secure mode agent cannot write |
| Agent Python subprocess tries to read original `.git` | OS denies in hardened mode |
| Agent Bash `git show HEAD:protected/path` | OS denies in hardened mode |
| Other MCP server or `Read` tool accesses protected path | Blocked by whole-process isolation / managed policy in hardened mode |

### Integration tests

- Use the official MCP SDK client or MCP Inspector to validate tool registration and schemas over stdio.
- Test multiple commits; test `HEAD`, SHA, annotated tag and permitted branch. Compare against known golden filtered results.
- Assert `git_log` doesn't return commit messages or protected filenames in secure defaults.
- Run red-team prompts asking Claude to read protected historical data; these are supplemental, not proof of safety.
- Test a *real* restricted process/mount namespace in deployment CI (when available), not only mocked permission functions.

## 9. Acceptance criteria / definition of done

### MVP functional acceptance

- [ ] `git_log`, `git_diff`, `git_show_commit`, `git_file_history` are callable through local MCP stdio.
- [ ] Server works in a generated fixture Git repo and in a separately approved test repo; no testing on ECSS10 secrets.
- [ ] Tool request parameters are strongly validated; `repository_root` is startup-only.
- [ ] Allowed patches remain useful and correct, including mixed allowed/forbidden commits.
- [ ] Forbidden filenames, file contents, binary patch data and raw Git stderr are not returned.
- [ ] Root and merge commits have explicit documented behavior.
- [ ] Tests cover the required matrix with zero unexplained failures.
- [ ] README contains installation, CLI invocation, troubleshooting, and non-guarantees.

### Security/hardening acceptance

- [ ] Agent cannot read original Git objects, protected current files or reach original GitLab through *any* tool/child process.
- [ ] Agent cannot modify service/policy, broaden sandbox, open privileged Unix sockets or access developer auth secrets.
- [ ] Broker is restricted to read-only Git operations, authenticates clients, and returns policy-validated results only.
- [ ] Verified by an OS-level integration test using the actual runtime/UID/mount/network configuration.
- [ ] Residual leaks (allowed-content secrets, commit metadata, embeddings in archives and symlinks, side channels) explicitly documented.

## 10. Implementation plan (do in order)

**Phase 1 — Scaffolding and policy.** Create project/venv, pin dependencies, define schema, implement path-policy unit tests; make denial behavior explicit. Build only with synthetic repositories.

**Phase 2 — Safe Git backend.** Implement startup repository check, ref resolver, immutable Git argv runner, output cap, timeouts and generic errors. No arbitrary command strings.

**Phase 3 — Safe read tools.** Implement `git_file_history` and `git_log` first; then `git_diff` and `git_show_commit` using approved-path discovery followed by per-approved-path patch creation. Write integration and adversarial tests before expanding supported options.

**Phase 4 — MCP and operator docs.** Wrap backend in MCP SDK v2, add structured return types, test stdio and Claude registration. Ensure stderr logging is sanitized and stdout remains MCP-only.

**Phase 5 — Advanced read APIs.** Add changed-files and blame, if they can be proven to obey the same policy. Reject unimplemented operations rather than exposing Git directly.

**Phase 6 — Security architecture.** Prototype with Claude's Bash sandbox and explicit file-tool denies. Then implement an independent privileged broker and an isolated agent workspace for confidential deployment. Verify OS and network barriers; do not promote the local prototype as equivalent.

## 11. Explicit non-goals and disclosure caveats

A perfectly implemented file-path filter **cannot** detect secrets accidentally committed into allowed files; it also cannot hide confidential commit subjects, author identities or other metadata if these are returned without review. It cannot protect against another MCP server, `Read` tool, external process, remote Git connection, or script with unsandboxed privileges. A Git MCP server is an information-release boundary **only when all other access routes are blocked independently**, preferably by an OS boundary.

A policy based on Git paths is not the same as content classification. For high-assurance deployments choose an explicit approved-path allowlist, quarantine allowed files with suspicious provenance, audit source/metadata exposure, and isolate the entire Claude Code process rather than only its Bash tool.

## 12. References (checked 2026-10-26)

- Official MCP Python SDK v2: https://py.sdk.modelcontextprotocol.io/
- MCP SDK server transport: https://py.sdk.modelcontextprotocol.io/run/
- Reference Git MCP implementation (SDK v1; study only): https://github.com/modelcontextprotocol/servers/tree/main/src/git
- Claude Code MCP setup: https://code.claude.com/docs/en/mcp
- Claude Code sandbox scope and limitations: https://code.claude.com/docs/en/sandboxing
- Git diff options (external diff, textconv, rename detection): https://git-scm.com/docs/git-diff
- Git diff-tree: https://git-scm.com/docs/git-diff-tree
- Git configuration and environment: https://git-scm.com/docs/git-config

---

## Copy/paste prompt for Codex

> Implement the project specified in `SAFE_GIT_MCP_IMPLEMENTATION_SPEC.md`. Create a **standalone Python 3.11+ MCP server using the current official MCP Python SDK v2**, with the requested read-only tools. Start by writing the security policy, fake-secret Git fixtures, and adversarial tests. Then build the Git backend and MCP layer. Do not execute arbitrary caller-supplied Git arguments, do not use shell=True, and do not expose raw Git stdout/stderr. Filter by approved Git paths *before obtaining or returning patch contents*, fail closed on all ambiguity, and use fixed, validated refs and paths. Do not access or alter ECSS10, its secrets, or its Git history during development. Finish by running tests/lint/type checks and documenting the exact commands/results and remaining limitations. The standalone local stdio mode is a prototype; document OS isolation as a separate hardening phase, not a guarantee provided by this implementation alone.
