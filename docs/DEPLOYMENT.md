# Local prototype deployment

Install the locked application into a trusted location. Store reviewed policy
outside all project-controlled paths; the server reads it at startup. Bind a
separately approved test repository, never production data for development tests.
Run `python -m safe_git_mcp --policy /absolute/admin/policy.toml` over stdio.
No TCP listener or authentication feature is implemented. Stop/restart after
policy/config changes or restored snapshots; dependency files survive, processes
do not. Run the development tests before registering a client.

This prototype requires the repository owner to match the server UID. It rejects
linked worktrees, shallow/bare layouts, alternates and unsupported local config.
Do not override ownership safety using `safe.directory=*`. Do not disable TLS or
package verification during installation. Ordinary execution requires no remote
access, SSH agent, GitHub token or production credentials.

An operator-managed policy/executable is required for confidentiality claims.
Local development does not prove the agent cannot edit them. Do not use this
prototype as an authenticated privileged service; follow HARDENED_DEPLOYMENT.md.

## Setup and diagnostics

Install/refresh with `uv sync --locked`. For each approved independent test repo:

```sh
.venv/bin/safe-git-mcp setup --name project-a \
  --repo /absolute/approved/test-repo --client eltex-claude --register
```

This writes a new 0600 policy in `~/.config/safe-git-mcp/project-a.toml`, checks
startup and an official SDK client stdio handshake, then invokes the client CLI
without a shell. Omit `--register` for a preview of the registration command.
Existing policy rules are reused without overwriting, only if the binding matches.
Policies with a different binding or invalid syntax are reported as conflicts.
A failed client registration leaves the policy intact for diagnosis; no automatic
registration deletion/replacement occurs. `--client` is one executable path/name,
not a shell command. Registration success means the client CLI exited successfully;
check `eltex-claude mcp list` for its effective connection state.

For existing policies:

```sh
.venv/bin/safe-git-mcp doctor --policy ~/.config/safe-git-mcp/policy.toml
```

CLI path arguments expand `~`; repository_root inside manually edited TOML must
remain absolute. Doctor checks missing prerequisites, layout and backend startup,
then performs initialize/list-tools over stdio with a 15-second deadline. It
returns fixed diagnostic text with no Git stderr, private config values or pointer
targets. It does not return history content. Repository rejection can still require
operator review of configuration; unsupported keys are not automatically removed.

No worktree redirection, OS-isolation deployment, privileged broker, or real
production-repository validation is performed by these commands. Root-owned policy
and executable placement remain an administrator responsibility in hardened mode.

## Docker alternative

See [DOCKER.md](DOCKER.md) for a self-contained stdio image and tested runtime
restrictions. No host Python setup is needed for container execution. The policy
uses `/repo` inside the container; the mounted repository remains read-only and
requires matching ownership. Docker does not add linked-worktree support or the
whole-agent confidentiality boundary.

## Compose alternative

[COMPOSE.md](COMPOSE.md) centralizes the container flags and uses `.env.example`
for per-project host paths and UID/GID interpolation. It preserves read-only
mounts and the fixed `/repo` policy binding without injecting the entire env file.
