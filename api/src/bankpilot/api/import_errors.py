"""文件职责：限定导入路由的错误契约，避免校验输入和 SQL 参数进入响应。"""

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from sqlalchemy.exc import SQLAlchemyError

from bankpilot.errors import StatementSizeError


class ImportRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def handle(request: Request) -> Response:
            try:
                return await handler(request)
            except RequestValidationError as exc:
                oversized = any(
                    isinstance(e.get("ctx", {}).get("error"), StatementSizeError)
                    or (e["type"] == "string_too_long" and e["loc"][-1] in {"data", "content"})
                    for e in exc.errors()
                )
                if oversized:
                    raise HTTPException(
                        413, {"code": "file_too_large", "message": "账单超过资源上限"}
                    ) from exc
                raise HTTPException(
                    422,
                    {
                        "code": "invalid_request",
                        "message": "请求格式无效，请刷新页面并核对导入配置",
                    },
                ) from exc
            except HTTPException as exc:
                if isinstance(exc.detail, dict):
                    raise
                code = {
                    401: "unauthenticated",
                    413: "file_too_large",
                    404: "import_not_found",
                    422: "invalid_structure",
                }.get(exc.status_code, "import_failed")
                raise HTTPException(
                    exc.status_code, {"code": code, "message": str(exc.detail)}
                ) from exc
            except (SQLAlchemyError, TimeoutError, OSError) as exc:
                raise HTTPException(
                    503,
                    {"code": "data_unavailable", "message": "结果暂无法确认，请查询或重试同一操作"},
                ) from exc

        return handle
