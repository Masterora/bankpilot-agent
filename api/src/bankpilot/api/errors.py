"""
文件职责：统一 HTTP 错误响应与异常处理。
主要内容：定义错误响应结构，将业务、校验、框架及未预期异常映射为稳定状态与错误码。
关键边界：响应不包含校验原文、数据库参数或内部异常详情。
"""
import logging
from collections.abc import Mapping

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException

from bankpilot.errors import PlanningError, StatementSizeError

logger = logging.getLogger(__name__)


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    detail: ErrorDetail


class ApiProblem(Exception):
    def __init__(self, status_code: int, code: str, message: str | None = None) -> None:
        self.status_code = status_code
        self.detail = ErrorDetail(code=code, message=message if message is not None else code)
        super().__init__(code)


def error_response(
    status: int, code: str, message: str, headers: Mapping[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content=ErrorResponse(detail=ErrorDetail(code=code, message=message)).model_dump(),
        headers=headers,
    )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiProblem)
    async def problem(request: Request, exc: ApiProblem) -> JSONResponse:
        return error_response(exc.status_code, exc.detail.code, exc.detail.message)

    @app.exception_handler(PlanningError)
    async def planning(request: Request, exc: PlanningError) -> JSONResponse:
        return error_response(exc.status, exc.code, exc.code)

    @app.exception_handler(RequestValidationError)
    async def validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        oversized = any(
            isinstance(error.get("ctx", {}).get("error"), StatementSizeError)
            or (error["type"] == "string_too_long" and error["loc"][-1] in {"data", "content"})
            for error in exc.errors()
        )
        if oversized:
            return error_response(413, "file_too_large", "账单超过资源上限")
        return error_response(422, "invalid_request", "请求格式无效，请核对填写内容")

    @app.exception_handler(HTTPException)
    async def framework(request: Request, exc: HTTPException) -> JSONResponse:
        # Only router/framework errors arrive here; application errors use ApiProblem.
        return error_response(
            exc.status_code, f"http_{exc.status_code}", "请求无法处理", exc.headers
        )

    async def unavailable(request: Request, exc: Exception) -> JSONResponse:
        logger.warning("API dependency unavailable: %s", type(exc).__name__)
        return error_response(503, "data_unavailable", "服务暂不可用，请重试；写操作请先核对结果")

    for kind in (SQLAlchemyError, TimeoutError, OSError):
        app.add_exception_handler(kind, unavailable)

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.error("Unhandled API failure: %s", type(exc).__name__)
        return error_response(500, "internal_error", "请求未完成，请稍后重试")
