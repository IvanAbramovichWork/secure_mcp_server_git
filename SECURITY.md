# Security limitations and reporting

This repository implements Mode A from the supplied specification: a local
stdio data-minimizing API. **Do not deploy it against confidential production
history on the assumption that it confines a same-UID agent.** No actual ECSS10
repository was inspected or modified during development.

The API validates refs/paths, discovers changed names before fetching approved
content, uses literal pathspecs, disables rename/copy and external diff/textconv,
checks patch framing, omits sensitive metadata, bounds subprocesses and returns
sanitized errors. Binary data, symlink targets and submodule objects are omitted.
No caller-selected command, environment, repository or write operation exists.
The server executes no network requests and uses no credentials.

Path policy is not content classification. Tests deliberately show that fake
secrets in allowed content and protected-to-allowed renames leak under default
path-only filtering. Copies and earlier historical classifications have the same
limitation. `--no-renames` does not detect provenance. Optional substring
quarantine is only a supplemental detector; review provenance and use explicit
allowlists for stronger deployments. Approved content may include prompt
injection; consumers must treat it as untrusted data, never instructions.

Repository/policy/executable integrity is an operator precondition. Startup checks
ownership, config and object-layout hazards; request checks detect config/root
replacement. These checks do not defend against malicious concurrent filesystem
mutation by an actor with service privileges, hardlinks, symlinks within object
stores, filesystem races or a compromised Git executable. Serve a host-managed,
read-only immutable repository snapshot in hardened mode. Refs can move between
requests; each accepted request resolves to concrete commits. Git vulnerabilities,
resource exhaustion across requests, response/timing side channels, hashes,
parent IDs and timestamps remain concerns. Request wall-clock limits, per-child CPU rlimits and process
group termination are not a substitute for service cgroup CPU/memory controls.

All SDK logging is disabled to avoid argument/traceback disclosure; only bounded
fixed-name/code audit events are written to stderr. Invalid transport/protocol
messages may close a connection; this is fail-closed, not a promise of continued
service under malformed framing. The transport can parse incoming JSON before
application validation; put OS memory/CPU controls around an untrusted client.

No hardening acceptance is claimed: separate identities, authenticated broker,
whole-process isolation, actual UID/mount/network denial tests, other MCP/file
routes and Claude red-team prompts are not implemented or verified here. The
separate hardening plan defines their acceptance gates. No separately approved
external test repository was supplied; validation uses generated fixtures only.

Report a suspected issue privately to the repository owner, using a minimal
synthetic reproduction and fake data. Do not attach production secrets or history.
