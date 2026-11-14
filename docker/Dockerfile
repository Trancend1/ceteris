# Image tunggal untuk API dan worker Ceteris R1 (ADR 0018).
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock LICENSE AGENTS.md ./
COPY ceteris ./ceteris
COPY server ./server
COPY configs ./configs
RUN uv sync --frozen --extra server --no-dev

ENV PATH="/app/.venv/bin:$PATH"
RUN useradd --create-home --uid 10001 ceteris && chown -R ceteris /app
USER ceteris

EXPOSE 8000
CMD ["uvicorn", "--factory", "ceteris_server.api:create_app", "--host", "0.0.0.0", "--port", "8000"]
