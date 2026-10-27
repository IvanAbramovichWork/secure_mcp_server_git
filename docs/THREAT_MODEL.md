# Threat model

Trust the operator-owned policy, executable, pinned dependencies, Git binary and
immutable repository snapshot. Distrust every MCP argument and all repository
content, messages, paths and attributes. The agent can submit hostile arguments
and invoke any other tools allowed by its runtime.

Data flow: raw request -> strict schema -> constrained commit resolver -> NUL
name/mode discovery -> shared path policy -> approved blob size/content checks ->
literal single-file diff -> framing validation -> bounded typed result.

Subprocesses run fixed argv with no shell, cleaned environment, fixed Git/worktree
binding, no replacement objects, global/system config, pager, prompts, external
diff or textconv. Repository-local includes/unsafe configuration and alternates
are rejected. Errors discard partial data and omit exception text. Commit subjects
and identities never enter result construction. Metadata-only audit logs contain
only fixed tool/outcome identifiers. Tool descriptions contain no repository data.

A malicious agent with another filesystem route bypasses this API. Same-UID
stdio, Bash-only deny rules and user-writable policies cannot form an OS boundary.
Even with OS isolation, allowed-content secrets, rename/copy provenance, permitted
filenames and metadata remain information-release policy concerns. Exact-substring
quarantine is optional and deliberately does not promise complete detection.
