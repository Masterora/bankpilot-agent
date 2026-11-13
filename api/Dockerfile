# API 启动不迁移数据库；发布时单独执行迁移。
FROM python:3.13-slim-trixie

COPY --from=ghcr.io/astral-sh/uv:0.12.9 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY alembic.ini ./
COPY migrations ./migrations
COPY src ./src
RUN uv sync --frozen --no-dev

RUN useradd --create-home --uid 10001 bankpilot \
    && chown -R bankpilot:bankpilot /app

USER bankpilot

EXPOSE 8000

# 发布脚本在启动之前单独执行迁移。
CMD ["uv", "run", "--no-sync", "uvicorn", "bankpilot.api.app:create_app", "--factory", "--no-proxy-headers", "--host", "0.0.0.0", "--port", "8000"]
