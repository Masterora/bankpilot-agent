"""
文件职责：提供服务状态接口。

主要内容：包含进程存活检查和数据库就绪检查。

关键边界：存活检查无外部依赖，就绪检查必须实际执行数据库查询。
"""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.api.dependencies import get_db_session
from bankpilot.api.schemas import HealthResponse

router = APIRouter(prefix="/api/v1", tags=["system"])


@router.get("/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/readyz", response_model=HealthResponse)
async def readyz(session: AsyncSession = Depends(get_db_session)) -> HealthResponse:
    await session.execute(text("SELECT 1"))
    return HealthResponse(status="ready")
