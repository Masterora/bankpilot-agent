"""
文件职责：验证 OpenRouter 适配器的结构化输出与隐私策略。
主要内容：检查严格 JSON Schema、Schema 兼容转换、数据收集禁用、推理强度和 Token 上限。
关键边界：使用 `MockTransport` 截获请求，不调用真实模型或使用真实 API Key。
"""

import json
from datetime import date
from typing import Any
from uuid import uuid4

import httpx
import pytest

from bankpilot.adapters.openrouter import OpenRouterModelGateway
from bankpilot.config import Settings
from bankpilot.domain.contracts import SupportedAction


@pytest.mark.asyncio
async def test_openrouter_uses_strict_schema_and_provider_policy() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "generation-1",
                "model": "provider/model",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "kind": "action",
                                    "tool": "query_transactions",
                                    "arguments": {
                                        "start_date": "2026-09-01",
                                        "end_date": "2026-09-01",
                                    },
                                    "user_message": "正在查询。",
                                }
                            )
                        }
                    }
                ],
                "usage": {"total_tokens": 20},
            },
        )

    settings = Settings(
        OPENROUTER_API_KEY="test-only-placeholder",
        MODEL_ID="provider/model",
        BANKPILOT_SESSION_SECRET="test-secret-with-more-than-32-characters",
    )
    async with httpx.AsyncClient(
        base_url="https://openrouter.ai/api/v1",
        transport=httpx.MockTransport(handler),
    ) as client:
        plan = await OpenRouterModelGateway(settings, client).plan(
            "查询今天的账单", today=date(2026, 9, 1), run_id=uuid4()
        )

    assert isinstance(plan.decision, SupportedAction)
    assert captured["response_format"]["type"] == "json_schema"
    assert captured["response_format"]["json_schema"]["strict"] is True
    schema_text = json.dumps(captured["response_format"]["json_schema"]["schema"])
    assert '"$defs"' not in schema_text
    assert '"$ref"' not in schema_text
    assert '"const"' not in schema_text
    assert '"query_transactions"' in schema_text
    assert captured["provider"] == {"require_parameters": True, "data_collection": "deny"}
    assert captured["reasoning"] == {"effort": "low"}
    assert captured["max_tokens"] == 1600
    assert "max_completion_tokens" not in captured
