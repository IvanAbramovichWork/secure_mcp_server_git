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
