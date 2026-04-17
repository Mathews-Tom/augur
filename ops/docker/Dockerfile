# Multi-stage build for every Augur worker kind.
#
# The same image runs every worker — selection happens via `CMD`
# overrides in the Kubernetes manifests under `ops/deploy/`. See
# `.docs/phase-5-scaling.md §8` for the full table of CMD strings.

# syntax=docker/dockerfile:1.7

# -----------------------------------------------------------------------------
# Stage 1: Build. Install dependencies into /build/.venv via uv.
# -----------------------------------------------------------------------------
FROM python:3.12-slim AS builder

ARG AUGUR_EXTRAS="distributed"

WORKDIR /build

# System dependencies: build tools for wheels and libpq for psycopg.
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        build-essential \
        ca-certificates \
        curl \
        libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Install uv and pin it so reproducible builds.
COPY --from=ghcr.io/astral-sh/uv:0.9.6 /uv /usr/local/bin/uv

# Copy metadata files first so layer caching works on dep-only changes.
COPY pyproject.toml uv.lock ./
COPY src/augur_signals/pyproject.toml src/augur_signals/pyproject.toml
COPY src/augur_labels/pyproject.toml src/augur_labels/pyproject.toml
COPY src/augur_format/pyproject.toml src/augur_format/pyproject.toml

# Resolve and lock workspace dependencies; installs the distributed
# extra for multi-process deployments.
RUN uv sync --frozen --no-dev --extra ${AUGUR_EXTRAS}

# Copy source last.
COPY src/ src/
COPY config/ config/

# Build the wheels into the venv.
RUN uv sync --frozen --no-dev --extra ${AUGUR_EXTRAS}

# -----------------------------------------------------------------------------
# Stage 2: Runtime. Slim image with only the venv + config.
# -----------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

RUN apt-get update \
    && apt-get install --no-install-recommends -y libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system augur \
    && useradd --system --gid augur --home-dir /app augur

WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/src" \
    AUGUR_CONFIG_DIR="/app/config" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY --from=builder --chown=augur:augur /build/.venv /app/.venv
COPY --from=builder --chown=augur:augur /build/src /app/src
COPY --from=builder --chown=augur:augur /build/config /app/config

USER augur

# Default to the monolith engine; Kubernetes manifests override CMD
# per worker kind (poller, feature, detector, manipulation, calibration,
# dedup, context_format, llm).
ENTRYPOINT ["python", "-m"]
CMD ["augur_signals.engine"]
