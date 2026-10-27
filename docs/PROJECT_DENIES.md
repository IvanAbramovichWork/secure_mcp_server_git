# Additional project-level denies

The mandatory operator TOML policy remains the baseline. A project can add deny
patterns at server startup using `SAFE_GIT_PROJECT_DENY_PATHS`, whose value is a
JSON **array of strings**. This uses the standard MCP registration `env` field;
it does not add a custom `deny_paths` field to the MCP configuration format, and
the server does not auto-read `.mcp.json` from a Git repository.

For every API and historical path:

```text
allowed = operator policy allows it AND no project deny pattern matches
```

An operator allow exception cannot override a project deny. Project rules cannot
change repository binding, operator allowlist/denies/exceptions, limits or metadata
disclosure. Clearing the variable or using `[]` removes only the optional startup
additions; it cannot grant anything forbidden by the operator policy. Existing
`project_deny_paths` in operator TOML, if explicitly declared, are retained and
runtime patterns are appended rather than substituted.

Rules are frozen in memory for that server process. Reconnect/restart after editing
a registration or env file. No MCP tool accepts project rules as arguments.

## Native .mcp.json

For a local prototype, create a project-root `.mcp.json` using standard registration
fields (replace the installation/policy paths):

```json
{
  "mcpServers": {
    "safe-git": {
      "type": "stdio",
      "command": "/home/your-user/secure_mcp_server_git/.venv/bin/python",
      "args": [
        "-m", "safe_git_mcp",
        "--policy", "/home/your-user/.config/safe-git-mcp/project-a.toml"
      ],
      "env": {
        "SAFE_GIT_PROJECT_DENY_PATHS": "[\"internal/**\", \"notes/private/**\", \"**/*.local.json\"]"
      }
    }
  }
}
```

The JSON array is encoded as a string because MCP process environment values are
strings. Operator `repository_root` for this native example remains the approved
absolute host repository path. No policy is optional: missing/invalid operator
configuration refuses startup even when project rules are valid.

## Compose .mcp.json

Rebuild the image after updating the code: older images do not implement this
startup variable. Use the Compose guide to create the external env file and a
Docker TOML policy with `repository_root = "/repo"`. The registration can add
rules without changing that operator policy:

```json
{
  "mcpServers": {
    "safe-git": {
      "type": "stdio",
      "command": "docker",
      "args": [
        "compose",
        "--file", "/home/your-user/secure_mcp_server_git/compose.yaml",
        "--env-file", "/home/your-user/.config/safe-git-mcp/project-a.env",
        "run", "--rm", "--no-deps", "-T", "--interactive", "safe-git"
      ],
      "env": {
        "SAFE_GIT_PROJECT_DENY_PATHS": "[\"internal/**\", \"notes/private/**\"]"
      }
    }
  }
}
```

The shared Compose service explicitly forwards only this dedicated application
variable. It still does not inject the entire env file. You can instead put this
line in the per-project `.env` file:

```dotenv
SAFE_GIT_PROJECT_DENY_PATHS='["internal/**", "notes/private/**"]'
```

Compose defaults to `[]` only when the variable is **unset**. An explicitly empty
value is invalid and must not silently disable intended restrictions. Standard
Compose precedence applies: the registration's process environment overrides the
env-file value, rather than combining the two sources. Use one source for the
complete optional project list; operator rules always remain in force. Stale
shell exports can also override the env file; clear them when selecting a project.

For direct Docker launches, explicitly pass the variable into the container with
`--env SAFE_GIT_PROJECT_DENY_PATHS` (after setting it on the Docker client's process)
in addition to all the security/mount flags in DOCKER.md. Setting `env` in a
registration for `docker` alone does not automatically pass arbitrary variables
through into containers; the Compose file already includes the necessary mapping.

## Validation, diagnostics and limits

The same case-sensitive repository-relative component glob syntax as the operator
policy applies: `*` and `?` stay inside a component, `**` spans zero or more
components. No regex, gitignore negation, absolute/traversal paths, bracket classes,
NUL or Git pathspec syntax is accepted. Unicode patterns must be valid UTF-8.

- At most 128 combined project patterns (operator project entries plus startup entries).
- At most 256 characters and 32 components per pattern.
- At most 65,536 UTF-8 bytes in the startup JSON value.
- Only JSON arrays of strings are accepted; malformed JSON, non-string entries,
  unsupported patterns and explicit empty values fail startup with generic errors.

`doctor` reports `PROJECT_DENIES_INVALID` without echoing values. It applies the
same rules and forwards the dedicated variable to its stdio handshake child.
`setup` checks these runtime restrictions before writing a new policy, but never
persists environment-derived patterns into operator TOML or its printed registration
command. Configure each client registration/environment explicitly; invoking native
setup with the variable set does not permanently save project settings.

## Trust and limitations

These project rules only add restrictions through this API. A person who can edit
the entire `.mcp.json` can also change its command, policy path or Docker mounts;
that file is not a strong confidentiality boundary. For hardened deployment keep
launch configuration, server and operator policy administrator-managed and isolate
the whole agent. Omission of optional rules can reveal operator-approved data,
so mandatory restrictions always belong in operator policy. Local stdio, allowed
content/provenance and linked-worktree limitations are unchanged.

Tests use synthetic Git repositories with fake secrets and cover every API,
exception precedence, immutable composition, invalid inputs, startup/doctor/setup,
explicit native MCP env and real Docker/Compose forwarding. No real ECSS10 history
is inspected. Actual Claude project-config approval/registration remains a host-side
step; tests exercise the official SDK process-environment behavior.
