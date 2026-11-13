"""RSA2 sandbox checkout and queries using Alipay's official SDK. No production gateway."""

import asyncio
import base64
import json
from collections.abc import Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from alipay.aop.api.AlipayClientConfig import AlipayClientConfig  # type: ignore[import-untyped]
from alipay.aop.api.DefaultAlipayClient import DefaultAlipayClient  # type: ignore[import-untyped]
from alipay.aop.api.request.AlipayTradePagePayRequest import (  # type: ignore[import-untyped]
    AlipayTradePagePayRequest,
)
from alipay.aop.api.request.AlipayTradeQueryRequest import (  # type: ignore[import-untyped]
    AlipayTradeQueryRequest,
)
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from bankpilot.config import Settings
from bankpilot.db.models import AlipayOrderRecord
from bankpilot.errors import PlanningError

GATEWAY = "https://openapi-sandbox.dl.alipaydev.com/gateway.do"
ALIPAY_TIMEZONE = ZoneInfo("Asia/Shanghai")


class _ShanghaiAlipayClient(DefaultAlipayClient):  # type: ignore[misc]
    """SDK 3.7 writes a naive timestamp and has no public clock injection point.

    Normalize at its common-parameter hook, before the SDK signs either kind of
    request. Keep this compatibility shim covered by real SDK signing tests;
    never change process TZ or patch the SDK's shared datetime module.
    """

    def _DefaultAlipayClient__get_common_params(self, params: dict[str, Any]) -> dict[str, Any]:
        params["timestamp"] = datetime.now(ALIPAY_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")
        result: dict[str, Any] = super()._DefaultAlipayClient__get_common_params(params)
        return result


def pem(value: str, label: str) -> bytes:
    value = value.replace("\\n", "\n").strip()
    if value.startswith("-----BEGIN"):
        return value.encode()
    return f"-----BEGIN {label}-----\n{value}\n-----END {label}-----".encode()


async def sdk_work[T](function: Callable[[], T]) -> T:
    """Do not release admission while a cancelled synchronous SDK call is still running."""
    task = asyncio.create_task(asyncio.to_thread(function))
    cancelled = False
    while True:
        try:
            result = await asyncio.shield(task)
            break
        except asyncio.CancelledError:
            if task.cancelled():
                raise
            cancelled = True
    if cancelled:
        raise asyncio.CancelledError
    return result


class AlipaySandbox:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        try:
            private = serialization.load_pem_private_key(
                pem(settings.alipay_private_key.get_secret_value(), "RSA PRIVATE KEY"),
                password=None,
            )
            public = serialization.load_pem_public_key(
                pem(settings.alipay_public_key.get_secret_value(), "PUBLIC KEY")
            )
            if (
                not isinstance(private, rsa.RSAPrivateKey)
                or private.key_size < 2048
                or not isinstance(public, rsa.RSAPublicKey)
                or public.key_size < 2048
            ):
                raise ValueError("RSA2 keys require at least 2048 bits")
            self.public = public
            self.private_pem = private.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            ).decode()
        except (ValueError, TypeError) as exc:
            raise ValueError("Invalid Alipay sandbox RSA2 configuration") from exc

    def client(self) -> Any:
        config = AlipayClientConfig()
        config.app_id = self.settings.alipay_app_id
        config.server_url = GATEWAY
        config.app_private_key = self.private_pem
        config.alipay_public_key = pem(
            self.settings.alipay_public_key.get_secret_value(), "PUBLIC KEY"
        ).decode()
        config.sign_type = "RSA2"
        config.timeout = 10
        return _ShanghaiAlipayClient(config)  # No SDK logging of request payloads.

    def checkout(self, order: AlipayOrderRecord) -> str:
        request = AlipayTradePagePayRequest()
        request.notify_url = (
            self.settings.integration_public_url.rstrip("/") + "/api/v1/integrations/alipay/notify"
        )
        request.biz_content = {
            "out_trade_no": order.id.hex,
            "total_amount": format(order.amount, ".2f"),
            "subject": order.subject,
            "product_code": "FAST_INSTANT_TRADE_PAY",
            "time_expire": order.expires_at.astimezone(ALIPAY_TIMEZONE).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
        }
        try:
            url: str = self.client().page_execute(request, http_method="GET")
            if not url.startswith(GATEWAY + "?"):
                raise ValueError("gateway")
            return url
        except Exception as exc:
            raise PlanningError("alipay_checkout_failed", 502) from exc

    async def query(self, order_id: str) -> dict[str, Any]:
        def execute() -> dict[str, Any]:
            request = AlipayTradeQueryRequest()
            request.biz_content = {"out_trade_no": order_id}
            result: dict[str, Any] = json.loads(self.client().execute(request))
            return result

        try:
            return await sdk_work(execute)
        except Exception as exc:
            raise PlanningError("alipay_query_failed", 502) from exc

    def verify(self, data: dict[str, str]) -> None:
        try:
            if data.get("sign_type") != "RSA2":
                raise ValueError("signature algorithm")
            content = "&".join(
                f"{k}={v}" for k, v in sorted(data.items()) if k not in {"sign", "sign_type"} and v
            )
            self.public.verify(
                base64.b64decode(data["sign"], validate=True),
                content.encode(),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        except (InvalidSignature, ValueError, KeyError) as exc:
            raise PlanningError("alipay_signature_invalid", 401) from exc
