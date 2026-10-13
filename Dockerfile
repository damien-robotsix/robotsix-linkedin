# syntax=docker/dockerfile:1

# ---- builder: resolve the venv from uv.lock (single source of truth) ----
FROM ghcr.io/astral-sh/uv:python3.14-trixie-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# git is needed to fetch the robotsix-* git dependencies pinned in uv.lock.
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first (layer cache); the lockfile is authoritative.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --no-install-project

# Then install the project itself against the same locked graph.
COPY src/ src/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# ---- runtime: ship only the resolved venv ----
FROM python:3.14-slim AS runtime

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH" \
    UV_PYTHON_DOWNLOADS=never

EXPOSE 8000

CMD ["python", "-m", "linkedin_service"]
