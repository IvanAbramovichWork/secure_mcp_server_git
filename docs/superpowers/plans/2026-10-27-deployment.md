# Easier local deployment

Use TDD in the existing cloud checkout. Preserve the MCP interface and repository trust boundary.

1. Test CLI doctor with synthetic repositories: valid startup, malformed/missing policy, missing prerequisites, linked worktree rejection without reading its pointer, unsafe configuration, sanitized diagnostics. Implement operator-only diagnostics and a real official-client stdio handshake.
2. Test setup: tilde expansion, absolute generated policy, safe per-project names, complete policy defaults, no overwrite of existing rules, no policy creation on rejected repositories, optional registration using argv rather than shell, registration failure reporting. Implement setup with --name/--repo/--config-dir/--client/--register; print exact registration argv without executing by default.
3. Document install/setup/doctor and multi-project examples, explicit linked-worktree limitation, and local-mode limits. Test CLI and full suite, lint/type/build, review diff and publish to GitHub.

No real ECSS10 access. Unsupported worktrees are explained, never auto-rebound to original history. Operator-provided repository path is used only by setup/doctor/startup, never accepted from MCP. No policy weakening or implicit registration replacement.

## Results

- CLI test-first cycle: 9 expected initial failures -> passing implementation.
- Fresh review: policy-creation race reproduced with 2 RED tests, fixed with O_EXCL creation decision -> GREEN. Prlimit test fixture narrowed to avoid mocking Git availability.
- Full final suite: 127 passed; Ruff lint/format clean; strict mypy clean; wheel/sdist built.
- Registration tested using a synthetic client executable; actual eltex-claude unavailable. No production or ECSS10 reads, no linked-worktree support added, no automatic registration replacement. No remaining review findings.
