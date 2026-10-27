# Separate production-hardening plan — not implemented

Local stdio is not Mode B. No production confidential-data deployment is approved
by the local prototype's tests.

1. Run a read-only trusted history service under a dedicated `gitreader` identity
   or outside the agent container. Mount a host-managed immutable repository
   snapshot read-only. Lock down policy, application, dependency environment and
   Git executable against agent writes. Use explicit reviewed allowlists and
   review protected-to-allowed rename/copy provenance across history.
2. Implement an authenticated Unix socket broker or protected HTTP transport and
   an unprivileged MCP bridge. Scope socket/client authorization; reuse identical
   request schemas, limits, path policy and sanitized results. Never introduce an
   arbitrary Git-command endpoint. Verify peer credentials/authentication and
   reject unauthorized clients before repository access.
3. Put the entire agent and all its subprocesses/tools in a separate UID/container
   and mount namespace. Provide an approved workspace with protected current files
   absent and no original repository, object-store, alternate or alias mounts.
   No developer credentials, original GitLab network route, SSH agent, Docker
   socket, privileged service sockets or arbitrary sudo. Enforce network policy
   independently of agent-controlled settings. Apply cgroup CPU/memory/process
   limits and inbound transport-size/rate limits to service and bridge.
4. Add deployment CI using the actual runtime identity/mount/network setup and
   synthetic protected data. Require OS denial of Python file reads, Bash
   `git show HEAD:protected/path`, `.git` pointer/common-dir/alternates access,
   protected current files, service/policy edits, credential/socket access and
   remote fetch. Test every configured file tool, MCP, hook and LSP route; mock
   permission functions are insufficient. A missing isolation runtime must mark
   the gate UNRUN, never passing or silently skipped as successful.
5. Verify authenticated approved reads still work through the bridge, hostile
   paths/refs remain denied, timeouts kill descendants, concurrent/rate-limited
   requests remain bounded, and sensitive fields never enter logs. Run supplemental
   red-team prompts under Claude Code. Audit allowed content, identities, path
   disclosure, hashes, archive embeddings, provenance and timing/size side channels.
6. Publish an operator acceptance record with exact UID/mount/network configuration,
   tool inventory, immutable artifact hashes, policy review, test commands/results,
   recovery/rotation plan and unresolved risks. Only that record can justify a
   stronger isolation claim. Do not elevate the same-UID stdio child or equate a
   Bash sandbox configuration with whole-process isolation.

Acceptance requires both positive broker functionality and negative OS/network
access tests. This repository does not contain the broker or claim those checks
have run; they require a separately authorized deployment task and infrastructure.
