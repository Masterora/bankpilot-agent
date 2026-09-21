"""Application resource cleanup checks; no database or model connections."""

import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from bankpilot.api.app import create_app
from bankpilot.config import Settings


class LifecycleChecks(unittest.IsolatedAsyncioTestCase):
    async def check_cleanup(self, failure=None, *, injected=False):
        engine = Mock(dispose=AsyncMock())
        client = Mock(aclose=AsyncMock())
        workers = []

        async def worker():
            workers.append(asyncio.current_task())
            await asyncio.Event().wait()

        async def report_worker():
            if failure == "worker":
                raise RuntimeError("worker failed")
            await worker()

        processor = Mock(
            reconcile_interrupted=AsyncMock(
                side_effect=RuntimeError("startup failed") if failure == "startup" else None
            ),
            recover_expired=worker,
        )
        with (
            patch("bankpilot.api.app.create_engine", return_value=engine) as create_engine,
            patch("bankpilot.api.app.create_session_factory", return_value=Mock()),
            patch("bankpilot.api.app.httpx.AsyncClient", return_value=client) as create_client,
            patch("bankpilot.api.app.RunProcessor", return_value=processor),
            patch("bankpilot.api.app.ReportProcessor", return_value=Mock(run=report_worker)),
        ):
            dependencies = (
                {"session_factory": Mock(), "model_gateway": Mock(), "assistant_gateway": Mock()}
                if injected else {}
            )
            app = create_app(settings=Settings(_env_file=None), **dependencies)

            async def run():
                async with app.router.lifespan_context(app):
                    await asyncio.sleep(0)

            if failure:
                with self.assertRaisesRegex(RuntimeError, f"{failure} failed"):
                    await run()
            else:
                await run()
            self.assertTrue(all(task.done() for task in workers))
            if injected:
                create_engine.assert_not_called()
                create_client.assert_not_called()
                engine.dispose.assert_not_awaited()
                client.aclose.assert_not_awaited()
            else:
                engine.dispose.assert_awaited_once()
                client.aclose.assert_awaited_once()

    async def test_normal_shutdown(self):
        await self.check_cleanup()

    async def test_startup_failure(self):
        await self.check_cleanup("startup")

    async def test_worker_failure(self):
        await self.check_cleanup("worker")

    async def test_injected_resources_remain_owned_by_caller(self):
        await self.check_cleanup(injected=True)


if __name__ == "__main__":
    unittest.main()
