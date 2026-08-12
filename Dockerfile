# syntax=docker/dockerfile:1

ARG NODE_VERSION=24
ARG PYTHON_VERSION=3.12

FROM node:${NODE_VERSION}-bookworm-slim AS frontend-build
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM ghcr.io/astral-sh/uv:0.12.2 AS uv

FROM python:${PYTHON_VERSION}-slim-bookworm AS python-deps
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0
WORKDIR /app
COPY --from=uv /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime
ARG APP_UID=10001
ARG APP_GID=10001
ENV DATA_DIR=/data \
    FRONTEND_DIST_PATH=/app/frontend/dist \
    PATH=/app/.venv/bin:${PATH} \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install --yes --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid "${APP_GID}" app \
    && useradd --uid "${APP_UID}" --gid "${APP_GID}" --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /app/frontend /data \
    && chown app:app /data

WORKDIR /app
COPY --from=python-deps --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app backend/ /app/backend/
COPY --from=frontend-build --chown=app:app /build/frontend/dist/ /app/frontend/dist/

USER app:app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read()"]
CMD ["python", "-m", "uvicorn", "backend.app.asgi:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
