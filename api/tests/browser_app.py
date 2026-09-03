"""
文件职责：为浏览器验收提供可启动的测试 API 入口。
主要内容：创建注入 `FakeModelGateway` 的 FastAPI 应用实例。
关键边界：本模块仅供测试启动，生产运行时不得导入。
"""

from bankpilot.api.app import create_app
from tests.fakes.model_gateway import FakeModelGateway

app = create_app(model_gateway=FakeModelGateway())
