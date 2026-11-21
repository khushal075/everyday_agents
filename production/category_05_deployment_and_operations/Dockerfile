FROM ghcr.io/astral-sh/uv:0.12.23@sha256:61d393e44e249f2e4b526b6c7ddcecce245946826e608e11c93ad4f5bba55b21 AS uv
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

COPY --from=uv /uv /uvx /usr/local/bin/
WORKDIR /app
ENV UV_LINK_MODE=copy     UV_PYTHON_DOWNLOADS=never     PYTHONUNBUFFERED=1     PYTHONDONTWRITEBYTECODE=1     PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock README.md ./
COPY src/ src/
COPY production/ production/
RUN uv sync --locked --no-dev --no-editable     && groupadd --gid 10001 agents     && useradd --uid 10001 --gid agents --no-create-home agents     && mkdir /data     && chown agents:agents /data

USER agents
CMD ["python", "-m", "uvicorn", "production.api:app", "--host", "0.0.0.0", "--port", "8000"]
