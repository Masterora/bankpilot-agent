"""Authenticated integration settings and provider-authenticated callbacks."""

import asyncio
from urllib.parse import parse_qsl
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.adapters.alipay_sandbox import AlipaySandbox
from bankpilot.adapters.feishu import FeishuAdapter
from bankpilot.api.dependencies import get_app_settings, get_current_user, get_db_session
from bankpilot.config import Settings
from bankpilot.db.models import AlipayOrderRecord, FeishuBindingRecord, UserRecord
from bankpilot.domain.integrations import (
    BindingCodeView,
    IntegrationStatus,
    SandboxOrderView,
    SandboxPaymentInput,
)
from bankpilot.errors import PlanningError
from bankpilot.services import integrations as service
from bankpilot.services.security_admission import SecurityAdmission

router = APIRouter(prefix="/api/v1/integrations", tags=["integrations"])


def require_ready(request: Request) -> None:
    if not getattr(request.app.state, "security_ready", False):
        raise PlanningError("data_unavailable", 503)


def feishu(request: Request) -> FeishuAdapter:
    require_ready(request)
    adapter: FeishuAdapter | None = getattr(request.app.state, "feishu", None)
    if adapter is None:
        raise PlanningError("feishu_unavailable", 404)
    return adapter


def alipay(request: Request) -> AlipaySandbox:
    require_ready(request)
    adapter: AlipaySandbox | None = getattr(request.app.state, "alipay_sandbox", None)
    if adapter is None:
        raise PlanningError("alipay_sandbox_unavailable", 404)
    return adapter


async def bounded_body(request: Request, maximum: int = 65536) -> bytes:
    body = bytearray()
    async with asyncio.timeout(3):
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > maximum:
                raise PlanningError("callback_too_large", 413)
    return bytes(body)


@router.get("", response_model=IntegrationStatus)
async def status(
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_app_settings),
) -> IntegrationStatus:
    binding = await session.get(FeishuBindingRecord, user.id)
    valid = bool(
        binding
        and binding.open_id
        and binding.app_id == settings.feishu_app_id
        and binding.tenant_key == settings.feishu_tenant_key
    )
    return IntegrationStatus(
        feishu_enabled=settings.feishu_enabled,
        feishu_bound=valid,
        feishu_identity=("…" + binding.open_id[-6:])
        if valid and binding and binding.open_id
        else None,
        alipay_sandbox_enabled=settings.alipay_sandbox_enabled,
    )


@router.post("/feishu/binding-code", response_model=BindingCodeView)
async def binding_code(
    request: Request,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_app_settings),
) -> BindingCodeView:
    feishu(request)
    result = await service.binding_code(session, settings, user.id)
    await session.commit()
    return BindingCodeView.model_validate(result)


@router.post("/feishu/unbind", status_code=204)
async def unbind(
    user: UserRecord = Depends(get_current_user), session: AsyncSession = Depends(get_db_session)
) -> None:
    await service.unbind(session, user.id)
    await session.commit()


@router.post("/feishu/events")
async def events(request: Request) -> dict[str, str]:
    adapter = feishu(request)
    async with asyncio.timeout(2.5):
        data = adapter.event(await bounded_body(request), dict(request.headers))
        if data.get("type") == "url_verification":
            challenge = data.get("challenge")
            if not isinstance(challenge, str) or not 1 <= len(challenge) <= 512:
                raise PlanningError("feishu_challenge_invalid", 422)
            return {"challenge": challenge}
        async with request.app.state.session_factory.begin() as session:
            await service.receive(session, adapter.settings, data)
    return {"msg": "success"}


@router.get("/alipay/orders", response_model=list[SandboxOrderView])
async def orders(
    request: Request,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[SandboxOrderView]:
    adapter = alipay(request)
    rows = (
        await session.scalars(
            select(AlipayOrderRecord)
            .where(
                AlipayOrderRecord.user_id == user.id,
                AlipayOrderRecord.app_id == adapter.settings.alipay_app_id,
                AlipayOrderRecord.seller_id == adapter.settings.alipay_seller_id,
            )
            .order_by(AlipayOrderRecord.created_at.desc())
            .limit(20)
        )
    ).all()
    return [await service.order_view(row, adapter) for row in rows]


@router.post("/alipay/orders", response_model=SandboxOrderView)
async def create_order(
    payload: SandboxPaymentInput,
    request: Request,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> SandboxOrderView:
    adapter = alipay(request)
    row = await service.create_order(session, adapter.settings, user.id, payload)
    result = await service.order_view(row, adapter, checkout=True)
    await session.commit()
    return result


@router.post("/alipay/orders/{order_id}/query", response_model=SandboxOrderView)
async def query_order(
    order_id: UUID,
    request: Request,
    user: UserRecord = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> SandboxOrderView:
    adapter = alipay(request)
    row = await session.get(AlipayOrderRecord, order_id)
    if (
        row is None
        or row.user_id != user.id
        or row.app_id != adapter.settings.alipay_app_id
        or row.seller_id != adapter.settings.alipay_seller_id
    ):
        raise PlanningError("alipay_order_not_found", 404)
    await service.limited(session, adapter.settings, user.id, "alipay_query")
    await session.commit()
    async with SecurityAdmission(request.app.state.session_factory, adapter.settings).lease(
        "integration", str(user.id), 2, 8
    ):
        data = await adapter.query(order_id.hex)
    await session.refresh(row, with_for_update=True)
    if data.get("code") == "10000":
        service.apply_payment(row, data, adapter.settings, notification=False)
    elif data.get("sub_code") != "ACQ.TRADE_NOT_EXIST":
        raise PlanningError("alipay_query_failed", 502)
    result = await service.order_view(row, adapter, checkout=True)
    await session.commit()
    return result


@router.post("/alipay/notify", response_class=Response)
async def notify(request: Request) -> Response:
    adapter = alipay(request)
    if (
        request.headers.get("content-type", "").split(";")[0].strip().lower()
        != "application/x-www-form-urlencoded"
    ):
        raise PlanningError("alipay_callback_invalid", 415)
    try:
        pairs = parse_qsl(
            (await bounded_body(request)).decode("utf-8"),
            keep_blank_values=True,
            strict_parsing=True,
            encoding="utf-8",
            errors="strict",
            max_num_fields=100,
        )
        data = dict(pairs)
        if len(data) != len(pairs):
            raise ValueError("duplicate fields")
        adapter.verify(data)
        order_id = UUID(hex=data["out_trade_no"])
    except (ValueError, KeyError, UnicodeError):
        raise PlanningError("alipay_callback_invalid", 422) from None
    async with request.app.state.session_factory.begin() as session:
        row = await session.get(AlipayOrderRecord, order_id, with_for_update=True)
        if row is None:
            raise PlanningError("alipay_order_not_found", 404)
        service.apply_payment(row, data, adapter.settings, notification=True)
    return Response("success", media_type="text/plain")
