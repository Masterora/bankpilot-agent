"""密码修改接口验收：复用随机临时数据库，不接触已有账户。"""

import asyncio

import httpx
from business import main, request

from bankpilot.api.app import create_app
from bankpilot.config import Settings


async def run(factory, url):
    settings = Settings(
        BANKPILOT_DATABASE_URL=url,
        BANKPILOT_SESSION_SECRET="password-acceptance-secret-9835-local-only",
        BANKPILOT_ENV="test",
        BANKPILOT_SESSION_COOKIE_SECURE=False,
    )
    app = create_app(settings=settings, session_factory=factory)
    app.state.settings = settings
    app.state.session_factory = factory
    transport = httpx.ASGITransport(app=app)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://acceptance") as first,
        httpx.AsyncClient(transport=transport, base_url="http://acceptance") as second,
        httpx.AsyncClient(transport=transport, base_url="http://acceptance") as other,
    ):
        old, new = "Old-password-9835!", "New-password-9835!"
        credentials = {"email": "password@example.com", "password": old}
        await request(first, "POST", "/auth/register", credentials, 201)
        await request(second, "POST", "/auth/login", credentials)
        await request(
            other,
            "POST",
            "/auth/register",
            {
                "email": "unrelated@example.com",
                "password": old,
            },
            201,
        )
        for proposed, expected in [
            ("weak", 422),
            (old, 400),
        ]:
            result = await request(
                first,
                "POST",
                "/auth/password",
                {
                    "new_password": proposed,
                },
                expected,
            )
            assert proposed not in str(result)
        await request(second, "GET", "/auth/me")
        await request(
            first,
            "POST",
            "/auth/password",
            {
                "new_password": new,
            },
            204,
        )
        await request(first, "GET", "/auth/me")
        await request(second, "GET", "/auth/me", status=401)
        await request(second, "POST", "/auth/password", {"new_password": old}, 401)
        await request(other, "GET", "/auth/me")
        await request(second, "POST", "/auth/login", credentials, 401)
        await request(second, "POST", "/auth/login", {**credentials, "password": new})
        print(
            "PASS password validation and session isolation"
        )


if __name__ == "__main__":
    asyncio.run(main(run))
