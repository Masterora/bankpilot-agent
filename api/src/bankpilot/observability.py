"""文件职责：按请求统计数据库和解析耗时。
关键边界：只记录路由模板和计数，不记录参数、正文、账户或 SQL 文本。
"""

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from time import perf_counter
from typing import Any
from uuid import uuid4

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("uvicorn.error")


@dataclass
class Timing:
    sql_ms: float = 0
    sql_count: int = 0
    connection_ms: float = 0
    parse_ms: float = 0


current_timing: ContextVar[Timing | None] = ContextVar("request_timing", default=None)


@contextmanager
def measure(field: str) -> Iterator[None]:
    start = perf_counter()
    try:
        yield
    finally:
        timing = current_timing.get()
        if timing is not None:
            setattr(timing, field, getattr(timing, field) + (perf_counter() - start) * 1000)


@contextmanager
def job_timing(job_id: str) -> Iterator[None]:
    timing = Timing()
    token = current_timing.set(timing)
    started = perf_counter()
    try:
        yield
    finally:
        logger.info(
            json.dumps(
                {
                    "job_id": job_id,
                    "total_ms": round((perf_counter() - started) * 1000, 2),
                    "sql_count": timing.sql_count,
                    "sql_ms": round(timing.sql_ms, 2),
                }
            )
        )
        current_timing.reset(token)


def instrument_engine(engine: AsyncEngine) -> None:
    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def before(
        conn: Any, cursor: Any, statement: Any, parameters: Any, context: Any, executemany: Any
    ) -> None:
        context.bankpilot_started = perf_counter()

    @event.listens_for(engine.sync_engine, "after_cursor_execute")
    def after(
        conn: Any, cursor: Any, statement: Any, parameters: Any, context: Any, executemany: Any
    ) -> None:
        timing = current_timing.get()
        if timing is not None:
            timing.sql_count += 1
            timing.sql_ms += (perf_counter() - context.bankpilot_started) * 1000


class RequestTimingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        timing = Timing()
        token = current_timing.set(timing)
        request_id = str(uuid4())
        start = perf_counter()
        status = 500
        finished_at: float | None = None
        response_timing: Timing | None = None

        async def timed_send(message: Message) -> None:
            nonlocal status, finished_at, response_timing
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (b"x-request-id", request_id.encode()),
                        (
                            b"server-timing",
                            (
                                f"db;dur={timing.sql_ms:.2f}, "
                                f"connection;dur={timing.connection_ms:.2f}, "
                                f"parse;dur={timing.parse_ms:.2f}"
                            ).encode(),
                        ),
                    ]
                )
                message["headers"] = headers
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                finished_at = perf_counter()
                response_timing = replace(timing)

        try:
            await self.app(scope, receive, timed_send)
        finally:
            route = scope.get("route")
            recorded = response_timing or timing
            logger.info(
                json.dumps(
                    {
                        "request_id": request_id,
                        "route": getattr(route, "path", "unmatched"),
                        "status": status,
                        "total_ms": round(((finished_at or perf_counter()) - start) * 1000, 2),
                        "sql_ms": round(recorded.sql_ms, 2),
                        "sql_count": recorded.sql_count,
                        "connection_ms": round(recorded.connection_ms, 2),
                        "parse_ms": round(recorded.parse_ms, 2),
                    }
                )
            )
            current_timing.reset(token)
