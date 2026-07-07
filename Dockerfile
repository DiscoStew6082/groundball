FROM python:3.12-slim

WORKDIR /app

# Install uv for fast package installs
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy pyproject.toml + lockfile and install deps (layer cache friendly)
COPY pyproject.toml uv.lock .
RUN uv sync --frozen --no-install-project

# Copy only the default app package; optional MCP source is intentionally not bundled.
COPY src/baseball_rag/ ./src/baseball_rag/
ENV PYTHONPATH=/app/src

EXPOSE 8001 7860

CMD ["uv", "run", "python", "-m", "uvicorn", "baseball_rag.api.server:app", "--host", "0.0.0.0", "--port", "8001"]
