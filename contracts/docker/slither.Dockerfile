# Local Slither runner: the pinned Foundry image plus a pinned Slither.
# CI installs the same versions natively (see .github/workflows/contracts.yml);
# the Slither version comes from contracts/.slither-version via `make slither`.
ARG FOUNDRY_IMAGE=ghcr.io/foundry-rs/foundry:v1.8.5
FROM ghcr.io/astral-sh/uv:0.11.3 AS uv
FROM ${FOUNDRY_IMAGE}

ARG SLITHER_VERSION
ENV UV_TOOL_DIR=/home/foundry/.uv-tools \
    UV_TOOL_BIN_DIR=/home/foundry/.local/bin \
    UV_PYTHON_INSTALL_DIR=/home/foundry/.uv-python \
    PATH=/home/foundry/.local/bin:${PATH}

COPY --from=uv /uv /usr/local/bin/uv
RUN uv tool install --python 3.12 "slither-analyzer==${SLITHER_VERSION}"

ENTRYPOINT ["slither"]
