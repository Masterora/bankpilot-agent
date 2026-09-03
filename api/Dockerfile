# 文件职责：构建 BankPilot API 生产镜像。
# 主要内容：安装锁定的 uv/Python 依赖，复制迁移与源码，创建非 root 运行用户。
# 关键边界：启动时先执行 Alembic 迁移，随后由同一进程接管 Uvicorn。
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

# 容器启动时先完成幂等迁移，再接管 API 主进程。
CMD ["sh", "-c", "uv run --no-sync alembic upgrade head && exec uv run --no-sync uvicorn bankpilot.api.app:create_app --factory --host 0.0.0.0 --port 8000"]
