# Docker stdio deployment

For shorter per-project commands, use [Compose and environment files](COMPOSE.md).
It shares the same image and restrictions described here.

Requires Linux kernel 5.12+ and Docker Engine 25+ (tested with Engine 28.4.0),
plus an approved standalone test repository. Python,
uv, Git and util-linux are installed inside the image; no host Python environment
is needed to run the service. No image is published to a registry by this project.
Build locally from the reviewed checkout:

```sh
git pull --ff-only
docker build -t safe-git-mcp:local .
```

The multi-stage image pins the official Python base digest and uv tool version,
installs Python dependencies from `uv.lock` with lock validation, and contains only
the installed application/runtime dependencies. The Docker context uses an
allowlist; `.git`, `.venv`, tests, local policies, credentials and unrelated files
are excluded. Git/util-linux are installed through signed Debian package metadata.
Builds need registry, Debian and PyPI access; running needs no network.
If an organization uses a TLS-inspecting proxy, forward its proxy configuration
and trusted CA only to the build (never disable TLS verification):

```sh
docker build --build-arg HTTP_PROXY --build-arg HTTPS_PROXY \
  --secret id=build_ca,src=/absolute/path/to/trusted-ca-bundle.pem \
  -t safe-git-mcp:local .
```

The optional CA secret is readable by APT's unprivileged downloader during the
build and is not copied into the runtime image. No proxy credentials or CA files
are required at runtime. Docker/build DNS routing must also reach the proxy.
 OS package
versions can change between rebuilds: this is not a bit-reproducible image.

## Policy and repository

Create a separate operator-managed Docker policy without overwriting an existing
one. Review its rules before use:

```sh
mkdir -p "$HOME/.config/safe-git-mcp"
(umask 077; set -C; cat config/policy.docker.example.toml > "$HOME/.config/safe-git-mcp/docker.toml")
```

The policy's **repository_root must be `/repo`**, the path inside the container.
Do not put a host path or `~` in that field. The host repository path belongs only
in the Docker bind mount. Keep the deployed policy outside the application and
agent workspace. Root-owned/admin-managed files are still required in a hardened
service; these local setup commands do not establish that privilege boundary.

For the commands below, set these to absolute host paths. Do not use ECSS10 or
production history for initial validation:

```sh
SAFE_GIT_REPO=/absolute/path/to/approved-standalone-test-repository
SAFE_GIT_POLICY="$HOME/.config/safe-git-mcp/docker.toml"
```

The repository bind uses `bind-recursive=readonly` to require read-only nested
mounts too; unsupported kernels/engines fail rather than silently leaving nested
mounts writable. Do not remove that flag to bypass the requirement.

The repository must contain a `.git` **directory** and be owned by the UID used to
run the container. The commands use your current UID:GID, preserving the backend
ownership check. Use a non-root account that can read the policy and repository.
Do not use `sudo docker run` with UID 0, chown original repositories, or set
`safe.directory=*` to bypass checks. Rootless/user-namespace remapping can change
bind-mount ownership; verify it with `doctor` and arrange ownership in a separately
approved test copy. It is not automatically remapped by the application.

## Check before registration

```sh
docker run --rm -i \
  --user "$(id -u):$(id -g)" \
  --network=none --read-only --cap-drop=ALL \
  --env HTTP_PROXY= --env HTTPS_PROXY= --env ALL_PROXY= --env NO_PROXY= \
  --env http_proxy= --env https_proxy= --env all_proxy= --env no_proxy= \
  --security-opt=no-new-privileges \
  --pids-limit=64 --memory=256m --cpus=1 \
  --tmpfs /tmp:rw,noexec,nosuid,size=16m,mode=1777 \
  --mount "type=bind,src=$SAFE_GIT_REPO,dst=/repo,readonly,bind-recursive=readonly,bind-propagation=rprivate" \
  --mount "type=bind,src=$SAFE_GIT_POLICY,dst=/policy/policy.toml,readonly" \
  safe-git-mcp:local doctor --policy /policy/policy.toml
```

Expected: JSON with `ok=true` and `code=READY`. Doctor uses an official SDK client
to initialize and list tools over stdio. It does not fetch file content. A `.git`
pointer returns `LINKED_WORKTREE_UNSUPPORTED`; Docker does not add worktree
support or follow pointers to unmounted original object stores. Missing mount
sources are rejected by Docker rather than silently creating directories.

## Register with Claude Code

Keep the same mount and restriction flags when registering:

```sh
eltex-claude mcp add --transport stdio --scope user safe-git-docker -- \
  docker run --rm -i \
  --user "$(id -u):$(id -g)" \
  --network=none --read-only --cap-drop=ALL \
  --env HTTP_PROXY= --env HTTPS_PROXY= --env ALL_PROXY= --env NO_PROXY= \
  --env http_proxy= --env https_proxy= --env all_proxy= --env no_proxy= \
  --security-opt=no-new-privileges \
  --pids-limit=64 --memory=256m --cpus=1 \
  --tmpfs /tmp:rw,noexec,nosuid,size=16m,mode=1777 \
  --mount "type=bind,src=$SAFE_GIT_REPO,dst=/repo,readonly,bind-recursive=readonly,bind-propagation=rprivate" \
  --mount "type=bind,src=$SAFE_GIT_POLICY,dst=/policy/policy.toml,readonly" \
  safe-git-mcp:local

eltex-claude mcp list
```

Use `claude` instead of `eltex-claude` for standard Claude Code. `-i` is required;
**do not add `-t`**, which introduces terminal framing. No ports are exposed.
Proxy variables are explicitly cleared because Docker client configuration may
otherwise inject proxy addresses or credentials into containers.
The client launches one container per connection; `--rm` removes it on exit.
The image's default command serves stdio with `/policy/policy.toml`. Old native
registrations are not changed automatically. Use a distinct name and policy per
project, mounting each project's approved repository at `/repo` in its own
container. Rebuild and reconnect after upgrading application/dependency files.

## What is and is not isolated

The flags constrain this server's filesystem writes, network, capabilities,
process count, memory and CPU. They do **not** isolate a Claude process running on
the host from host files, developer credentials or other tools. Allowing an agent
to invoke Docker or access its socket can grant extensive host control; never
mount the Docker socket or developer credentials into this container, and do not
grant an untrusted agent Docker-daemon access as a confidentiality boundary.
No authenticated broker or whole-agent isolation is implemented by this image.
Follow HARDENED_DEPLOYMENT.md for that separate service architecture. The complete
repository is readable by this trusted service container; path filtering controls
its MCP output. Allowed-content secrets and provenance limitations still apply.

Tests check actual container behavior with synthetic repositories, including
filtered responses, read-only writes, dropped capabilities, no-new-privileges,
no network route and pointer rejection. This is a service-container test, not the
full hardened-deployment acceptance suite. Actual Claude registration must be
verified on the deployment host.

## Reproduce the container checks

```sh
docker build -t safe-git-mcp:test .
uv sync --locked --group dev
SAFE_GIT_DOCKER_TESTS=1 uv run --locked pytest tests/test_docker_integration.py
```

Set `SAFE_GIT_DOCKER_IMAGE` to test another local image tag. Without explicit
opt-in, the normal unit suite marks Docker integration checks skipped. The Docker
CI job builds the image and explicitly executes them; a failed build/runtime is
not treated as a passing test. The daemon must see the same bind-mount filesystem
paths as the test runner. SELinux hosts may require administrator-reviewed mount
labels; do not disable enforcement globally to make the test pass.
