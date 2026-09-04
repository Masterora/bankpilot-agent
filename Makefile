# 文件职责：提供 BankPilot 本地开发与质量检查的统一命令入口。
# 主要内容：安装、迁移、数据初始化、API/Web 启动、分组测试与完整验证。
# 关键边界：`verify` 是提交前总门禁，必须覆盖 API 静态检查/测试和 Web 检查/测试/构建。
.PHONY: install migrate seed api web test verify

install:
	cd api && uv sync --all-groups
	cd web && npm install

migrate:
	cd api && uv run alembic upgrade head

seed:
	cd api && uv run bankpilot seed

api:
	cd api && uv run uvicorn bankpilot.api.app:create_app --factory --reload --port 8000

web:
	cd web && npm run dev

test:
	cd api && uv run pytest
	cd web && npm test -- --run

verify:
	cd api && uv run ruff check .
	cd api && uv run mypy src
	cd api && uv run pytest
	cd web && npm run lint
	cd web && npm test -- --run
	cd web && npm run build
