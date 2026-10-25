# The API as it runs in staging and production.
#
# Dependencies come from uv.lock, exactly as tested; the image holds the application, its
# migrations, and its scripts, and runs as an unprivileged user. Configuration comes from
# the environment (see deploy/ and docs/DEPLOYMENT.md at the repository root): nothing
# secret is ever copied in. The operator console is not included: it cannot send the
# operator key, so a deployed API could not serve it anything.

ARG PYTHON_VERSION=3.12

# --- Dependencies ---------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /build
COPY pyproject.toml uv.lock ./
# --frozen: the lockfile is the truth; a stale one fails the build instead of resolving.
RUN uv sync --frozen --no-dev --no-install-project

# --- Runtime --------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

RUN useradd --create-home --uid 10001 appuser
COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
# The evaluation package is imported by the API; the Phase 1 report is served by it.
COPY --chown=appuser:appuser app/ ./app/
COPY --chown=appuser:appuser evaluation/ ./evaluation/
COPY --chown=appuser:appuser scripts/ ./scripts/
COPY --chown=appuser:appuser migrations/ ./migrations/
COPY --chown=appuser:appuser alembic.ini PHASE1_REPORT.md ./

USER appuser
EXPOSE 8000

# For `docker run`; hosting platforms run their own checks against the same route.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8000') + '/api/v1/health/live', timeout=4)"

# One process per machine: the background loops run inside it, and an async server needs
# no extra workers for this load. Requests are logged by the API itself (as JSON in
# staging and production), so Uvicorn's own access log is off. Shutdown waits up to 25 s
# for replies in progress; the platform's kill timeout must be longer.
# - PORT: the port to listen on when the platform assigns one (Render); 8000 otherwise.
# - MIGRATE_ON_START=true: run migrations before serving, for a host with no release step
#   (Render's free plan). Fly runs them as its release command instead. A failed
#   migration stops the start, so the old version keeps serving.
# `exec` hands the process over to Uvicorn, so it receives the platform's stop signal.
CMD ["sh", "-c", "if [ \"$MIGRATE_ON_START\" = true ]; then alembic upgrade head || exit 1; fi; exec uvicorn app.main:app --host 0.0.0.0 --port \"${PORT:-8000}\" --no-access-log --no-server-header --timeout-graceful-shutdown 25"]
