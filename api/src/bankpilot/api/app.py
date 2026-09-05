"""
文件职责：创建 FastAPI 应用并组装运行时依赖。

主要内容：
- `create_app`：提供可替换的配置、会话工厂和模型网关，便于测试与扩展。
- `lifespan`：创建 HTTP 客户端、注册 `RunProcessor`、修复中断运行并释放资源。
- 应用组装：配置 CORS，并挂载 v1 路由。

关键边界：应用生命周期只关闭自身创建的引擎和客户端。
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from bankpilot.adapters.openrouter import OpenRouterModelGateway
from bankpilot.api.ledger import router as ledger_router
from bankpilot.api.reviews import router as reviews_router
from bankpilot.api.routes import router
from bankpilot.config import Settings, get_settings
from bankpilot.db.session import create_engine, create_session_factory
from bankpilot.ports import ModelGateway
from bankpilot.services.run_processor import RunProcessor


def create_app(
    settings: Settings | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    model_gateway: ModelGateway | None = None,
) -> FastAPI:
    """通过可替换端口构建应用，便于测试和扩展后续供应商。"""
    resolved_settings = settings or get_settings()
    managed_engine: AsyncEngine | None = None
    if session_factory is None:
        managed_engine = create_engine(resolved_settings.database_url)
        session_factory = create_session_factory(managed_engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """初始化共享客户端、修复运行状态，并关闭自身持有的资源。"""
        model_client: httpx.AsyncClient | None = None
        resolved_gateway = model_gateway
        if resolved_gateway is None:
            model_client = httpx.AsyncClient(
                base_url=str(resolved_settings.model_base_url).rstrip("/"),
                timeout=resolved_settings.model_timeout_seconds,
            )
            resolved_gateway = OpenRouterModelGateway(resolved_settings, model_client)

        app.state.settings = resolved_settings
        app.state.session_factory = session_factory
        app.state.run_processor = RunProcessor(session_factory, resolved_gateway)
        # 进程重启后无法安全继续原有后台任务，因此必须显式修复非终态记录。
        await app.state.run_processor.reconcile_interrupted()
        yield
        if model_client is not None:
            await model_client.aclose()
        if managed_engine is not None:
            await managed_engine.dispose()

    app = FastAPI(
        title="BankPilot Agent API",
        version="0.3.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Last-Event-ID"],
    )
    app.include_router(router)
    app.include_router(ledger_router)
    app.include_router(reviews_router)
    return app
