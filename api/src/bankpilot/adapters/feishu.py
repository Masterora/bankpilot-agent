"""Encrypted Feishu application events and private text replies; fixed official endpoints."""

import base64
import hashlib
import hmac
import json
import time
from typing import Any

import httpx
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from bankpilot.config import Settings
from bankpilot.errors import PlanningError


class FeishuAdapter:
    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self.settings, self.client = settings, client
        self.token = ""
        self.token_until = 0.0

    def event(self, body: bytes, headers: dict[str, str]) -> dict[str, Any]:
        try:
            outer = json.loads(body)
            encrypted = base64.b64decode(outer["encrypt"], validate=True)
            key = hashlib.sha256(
                self.settings.feishu_encrypt_key.get_secret_value().encode()
            ).digest()
            decryptor = Cipher(algorithms.AES(key), modes.CBC(encrypted[:16])).decryptor()
            unpadder = padding.PKCS7(128).unpadder()
            plain = decryptor.update(encrypted[16:]) + decryptor.finalize()
            data: dict[str, Any] = json.loads(unpadder.update(plain) + unpadder.finalize())
            header = data.get("header", {})
            token = (
                data.get("token") if data.get("type") == "url_verification" else header.get("token")
            )
            if not isinstance(token, str) or not hmac.compare_digest(
                token, self.settings.feishu_verification_token.get_secret_value()
            ):
                raise ValueError("token")
            if data.get("type") != "url_verification":
                stamp = headers.get("x-lark-request-timestamp", "")
                nonce = headers.get("x-lark-request-nonce", "")
                if not nonce or len(nonce) > 256 or abs(time.time() - int(stamp)) > 300:
                    raise ValueError("stale")
                expected = hashlib.sha256(
                    (stamp + nonce + self.settings.feishu_encrypt_key.get_secret_value()).encode()
                    + body
                ).hexdigest()
                if not hmac.compare_digest(expected, headers.get("x-lark-signature", "")):
                    raise ValueError("signature")
                if (
                    header.get("app_id") != self.settings.feishu_app_id
                    or header.get("tenant_key") != self.settings.feishu_tenant_key
                ):
                    raise ValueError("tenant")
            return data
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise PlanningError("feishu_callback_invalid", 401) from exc

    async def send(self, open_id: str, text: str, identity: str) -> None:
        try:
            if self.token_until <= time.monotonic():
                response = await self.client.post(
                    "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                    json={
                        "app_id": self.settings.feishu_app_id,
                        "app_secret": self.settings.feishu_app_secret.get_secret_value(),
                    },
                )
                response.raise_for_status()
                data = response.json()
                if data.get("code") != 0:
                    raise ValueError("token unavailable")
                self.token = data["tenant_access_token"]
                self.token_until = time.monotonic() + min(int(data["expire"]) - 60, 3600)
            response = await self.client.post(
                "https://open.feishu.cn/open-apis/im/v1/messages",
                params={"receive_id_type": "open_id"},
                headers={"Authorization": f"Bearer {self.token}"},
                json={
                    "receive_id": open_id,
                    "msg_type": "text",
                    "content": json.dumps({"text": text[:10000]}, ensure_ascii=False),
                    "uuid": identity,
                },
            )
            response.raise_for_status()
            if response.json().get("code") != 0:
                self.token_until = 0
                raise ValueError("delivery failed")
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise PlanningError("feishu_delivery_failed", 502) from exc
