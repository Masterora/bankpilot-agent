# 文件职责：提供 BankPilot 本地开发与质量检查的统一命令入口。
# 主要内容：安装、迁移、数据初始化、API/Web 启动与静态验证。
# 关键边界：`verify` 只覆盖静态检查与构建，业务验收需要页面和接口验证。
.PHONY: install migrate seed api web verify

install:
	cd api && uv sync --all-groups
	cd web && npm install

migrate:
	cd api && uv run alembic upgrade head

seed:
	cd api && uv run bankpilot seed

api: migrate
	cd api && uv run uvicorn bankpilot.api.app:create_app --factory --reload --port 8000

web:
	cd web && npm run dev

verify:
	cd api && uv run ruff check .
	cd api && uv run mypy src
	cd web && npm run lint
	cd web && npm run build
