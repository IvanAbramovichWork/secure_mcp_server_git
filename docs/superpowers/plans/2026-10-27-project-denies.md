# Additional project-level denies

Implement approved semantics: allowed = operator policy allows AND no project deny matches. No operator policy replacement, no repository selection or project rules accepted by MCP tools. Synthetic repositories only; never inspect ECSS10.

1. RED tests for immutable additive policy composition, allow-exception precedence, allowlist behavior, malformed JSON/types/globs and count/size bounds. Implement a bounded JSON-array startup variable SAFE_GIT_PROJECT_DENY_PATHS; no project .mcp.json auto-reading. Preserve existing trusted project_deny_paths if declared in TOML and only append runtime rules.
2. RED tests for native stdio registration via standard .mcp.json env semantics, all six APIs, sanitized startup failure and doctor/setup behavior. Apply rules once on startup using centralized Policy.allows. Doctor validates and forwards the same dedicated variable to its handshake child; setup never persists environment-derived project rules into operator policy.
3. Wire only the dedicated variable through Compose interpolation with [] default for unset values; explicit empty/invalid values must fail closed. Document native .mcp.json, Compose .mcp.json env and explicit docker --env forwarding. Keep existing runtime restrictions, no full env_file injection.
4. Rebuild image using supported cloud proxy/CA trust, run actual Docker/Compose negative tests. Fresh review, full suite/lint/type/build and GitHub push. Record residual local-mode/worktree limitations unchanged.

## Results

- Policy RED 24 -> GREEN, plus follow-up TOML preservation, missing denied blob, explicit-path and non-disclosure checks.
- Four native startup/doctor/setup/MCP regressions RED -> GREEN. Runtime setup restrictions validated before writes and not persisted into operator policy. Handshake forwards only the dedicated variable.
- Six real Docker/Compose tests failed against old image/mapping; rebuilt image plus dedicated Compose env mapping passed. Explicit empty values fail closed.
- Fresh security review: no actionable findings; independent focused suite 65 passed plus boundary/monotonicity checks.
- Final Docker-enabled suite: 180 passed, zero skips. Ruff lint/format, strict mypy and package builds passed. No real ECSS10 access or new hardening/worktree claims. Native .mcp.json and Compose examples documented; image rebuild/reconnect required.
