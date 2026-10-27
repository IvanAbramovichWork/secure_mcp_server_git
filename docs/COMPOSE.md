# Docker Compose and project environment files

Compose provides one shared stdio service definition and a small host configuration
file per project. No Python installation on the host is needed for deployment.
Requires the Docker/Linux prerequisites in [DOCKER.md](DOCKER.md), plus a current
Docker Compose v2 plugin supporting `volumes.bind.recursive` (tested with v2.40.3).
Older plugins that reject that field must be upgraded; do not remove the recursive
read-only requirement to work around it.

## Configure one project

After cloning or updating this installation, create separate files without
replacing existing configuration:

```sh
cd ~/secure_mcp_server_git
git pull --ff-only
mkdir -p "$HOME/.config/safe-git-mcp"
(umask 077; set -C; cat .env.example > "$HOME/.config/safe-git-mcp/project-a.env")
(umask 077; set -C; cat config/policy.docker.example.toml > "$HOME/.config/safe-git-mcp/project-a.toml")
```

Edit `project-a.env` with absolute **host** paths and the repository owner's UID/GID
(`id -u` and `id -g` show your own values). Example:

```dotenv
PROJECT_ROOT=/absolute/path/to/approved-standalone-test-repository
POLICY_FILE=/home/your-user/.config/safe-git-mcp/project-a.toml
HOST_UID=1000
HOST_GID=1000
SAFE_GIT_IMAGE=safe-git-mcp:local
COMPOSE_PROJECT_NAME=safe-git-project-a
```

Use a non-root account matching repository ownership. Paths with spaces can be
single-quoted; single quotes also keep literal dollar characters from being
interpolated. Do not use `~` or shell command substitutions such as `$(id -u)` in
the file. Enter the actual numeric IDs. Compose parses this file: never source or
eval it as a shell script. Shell-exported variables take precedence over env-file
values, so unset stale PROJECT_ROOT/POLICY_FILE/HOST_UID/HOST_GID overrides when
switching projects. `COMPOSE_PROJECT_NAME` is optional but should be distinct for
each project; there is no fixed container name.

Review `project-a.toml` access rules. Its `repository_root` stays `/repo`, the
fixed container mount destination. Host paths do not belong in TOML. Keep policies
operator-managed and outside agent-controlled projects. Never put credentials in
these env files. The local helper does not establish an administrative privilege
boundary; see [SECURITY.md](../SECURITY.md).

Local `.env`, `.env.*` and `*.env` files are Git-ignored; `.env.example` remains
tracked. A conventional `.env` beside compose.yaml also works if `--env-file` is
omitted, but explicit external per-project files avoid depending on the caller's
working directory. The Docker build context excludes all of these files.

## Build and check

From the installation checkout, using your project env file:

```sh
docker compose --file compose.yaml \
  --env-file "$HOME/.config/safe-git-mcp/project-a.env" build safe-git

docker compose --file compose.yaml \
  --env-file "$HOME/.config/safe-git-mcp/project-a.env" \
  run --rm --no-deps -T safe-git doctor --policy /policy/policy.toml
```

Expected doctor response: `ok=true`, `code=READY`. Missing variables fail during
Compose interpolation; missing bind sources fail without creating host directories.
The env template contains placeholders: replace them before using it. For a build
behind a custom CA/proxy, the explicit `docker build` example in DOCKER.md can
build the same local image tag; subsequent Compose runs use that image.

## Register with Claude Code

Use absolute paths so the client can start the service from any directory:

```sh
eltex-claude mcp add --transport stdio --scope user safe-git-project-a -- \
  docker compose \
  --file "$HOME/secure_mcp_server_git/compose.yaml" \
  --env-file "$HOME/.config/safe-git-mcp/project-a.env" \
  run --rm --no-deps -T --interactive safe-git

eltex-claude mcp list
```

Use `claude` for standard Claude Code. The compose.yaml file resolves its build
context relative to its own directory. `--interactive` preserves stdin even when
the client launches via pipes; `-T` disables terminal framing. Claude creates one
container per connection; `--rm` cleans it up on exit. The stdio connection belongs
to that process, so use `run` rather than starting a background service. There is
no HTTP listener, published port or auto-restart loop.

Existing client registrations are untouched. Use a new name or review/remove an
old entry in the client if replacing it. `pull_policy: never` requires a locally
built image and prevents an unexpected image pull during a connection attempt.
Changing files does not update an already running container: rebuild when the
application changes and reconnect after env/policy changes.

## Several projects and security scope

Create a second `.env` and TOML policy with its own PROJECT_ROOT, POLICY_FILE and
COMPOSE_PROJECT_NAME; register it under another client name. Each container sees
only its selected repository at `/repo` and its own policy. Tests exercise two
independent synthetic projects concurrently. Do not add mounts for all projects
to a shared instance or expose repository selection through MCP tool arguments.

The env file supplies Compose interpolation only. It is not declared as service
`env_file`, so unrelated variables and host paths are not injected into the
container. Proxy variables are explicitly emptied to override Docker-client
proxy injection. Shared settings enforce a read-only root and recursive read-only
repository mount, read-only policy, no network, dropped capabilities,
no-new-privileges, UID matching, memory/CPU/PID caps and a small noexec tmpfs.

Compose and its config files must be trusted. An actor allowed to edit compose.yaml
can weaken restrictions or add mounts; an actor controlling the env file can choose
a different repository/policy/image. Restrict their writes in hardened deployment.
Docker-daemon access can grant host control. This packages the trusted service;
it does not isolate a host-side agent or implement an authenticated broker.
Linked worktrees remain unsupported and are never redirected to original history.
No ECSS10 repository is accessed by the tests or setup development.

## Verification

```sh
docker build -t safe-git-mcp:test .
uv sync --locked --group dev
SAFE_GIT_DOCKER_TESTS=1 uv run --locked pytest tests/test_compose_integration.py
```

Tests use real Compose launches and official SDK stdio clients against generated
repositories containing fake secrets. CI builds the image and runs both direct
Docker and Compose suites. Without explicit Docker opt-in these runtime suites
are marked skipped, not validated. Actual eltex-claude registration needs to be
checked on the deployment host.
