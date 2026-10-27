# Official multi-platform Python image, pinned to the verified registry digest.
FROM python:3.12-slim-bookworm@sha256:6dd8b6dab6b3adc7812bab69eca5dbdc1a5cc690ad28306d234ffb4ef8ac9753 AS build
WORKDIR /opt/safe-git
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
# Optional build-only CA for corporate/cloud proxies; never disables verification.
RUN --mount=type=secret,id=build_ca,mode=0444 \
    if [ -f /run/secrets/build_ca ]; then export PIP_CERT=/run/secrets/build_ca; fi; \
    python -m pip install --no-cache-dir uv==0.12.23
COPY pyproject.toml uv.lock ./
COPY src/ ./src/
RUN --mount=type=secret,id=build_ca,mode=0444 \
    if [ -f /run/secrets/build_ca ]; then export SSL_CERT_FILE=/run/secrets/build_ca; fi; \
    uv sync --system-certs --locked --no-dev --no-editable --python /usr/local/bin/python

FROM python:3.12-slim-bookworm@sha256:6dd8b6dab6b3adc7812bab69eca5dbdc1a5cc690ad28306d234ffb4ef8ac9753
RUN --mount=type=secret,id=build_ca,mode=0444 \
    set -eu; \
    if [ -f /run/secrets/build_ca ]; then \
      printf 'Acquire::https::CaInfo "/run/secrets/build_ca";\n' > /tmp/apt-ca.conf; \
      export APT_CONFIG=/tmp/apt-ca.conf; \
    fi; \
    sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources; \
    apt-get update \
    && apt-get install -y --no-install-recommends git util-linux \
    && rm -rf /var/lib/apt/lists/* /tmp/apt-ca.conf \
    && groupadd --gid 10001 safegit \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /nonexistent safegit
WORKDIR /opt/safe-git
COPY --from=build /opt/safe-git/.venv /opt/safe-git/.venv
ENV PATH="/opt/safe-git/.venv/bin:/usr/local/bin:/usr/bin:/bin" \
    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 10001:10001
ENTRYPOINT ["/opt/safe-git/.venv/bin/safe-git-mcp"]
CMD ["--policy", "/policy/policy.toml"]
