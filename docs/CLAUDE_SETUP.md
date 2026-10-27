# Claude Code local prototype setup

For automatic local registration after `uv sync --locked`:

```sh
.venv/bin/safe-git-mcp setup --name project-a \
  --repo /absolute/approved/standalone-test-repo --client eltex-claude --register
```

Use `--client claude` for standard Claude Code. Repeat with a new name/policy for
each independent repository. Omit `--register` to preview the command. To diagnose
an existing policy, run `safe-git-mcp doctor --policy /absolute/policy.toml` using
the executable in this installation's `.venv/bin/`. Linked worktrees are explicitly
rejected and never redirected to original history. The manual alternative follows.

After installing at a trusted operator-owned path and reviewing the policy:

```sh
claude mcp add --transport stdio --scope user safe-git -- \
  /opt/safe-git-mcp/.venv/bin/python -m safe_git_mcp \
  --policy /etc/safe-git-mcp/policy.toml
claude mcp list
# In Claude Code: /mcp
```

Do not register through repository-controlled `.mcp.json`, and do not let the
agent modify the executable, dependencies, launch environment or policy. Check
current Claude Code configuration syntax and effective `/sandbox` settings on
the deployment machine; this integration was not tested with a Claude install.

The following partial settings illustrate the required categories, with fictional
paths. They are not a generated or complete policy:

```json
{
  "sandbox": {
    "enabled": true,
    "failIfUnavailable": true,
    "allowUnsandboxedCommands": false,
    "filesystem": {"denyRead": ["/srv/original-history", "/srv/protected-current"]}
  },
  "permissions": {"deny": ["Read(/srv/original-history/**)", "Read(/srv/protected-current/**)"]}
}
```

For an actual deployment, a trusted administrator must inventory every protected
working-tree path matched by every deny pattern (including nested matches),
protect the real Git common directory, worktree `.git` pointer, object directories,
alternates, symlink/hardlink aliases and other sensitive directories. This tool
intentionally does not inspect production paths to generate that inventory.
Protect newly added paths too: static expansion alone becomes stale. Prefer an
approved workspace with protected files absent and no original object-store mount.

Bash sandbox denyRead rules cover sandboxed commands and their children only.
Built-in Read/Grep/Edit, hooks, LSP, other MCP servers and unsandboxed paths need
independent managed controls. Block direct host/remote Git access, developer
credentials, SSH agents and privileged sockets. Denying `.git` alone leaves
protected current files exposed. Same-UID local stdio does not enforce these
controls; use whole-process OS isolation for confidential deployment.
