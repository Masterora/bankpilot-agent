# 文件职责：提供本地开发与验证的统一命令入口。
# 主要内容：安装、迁移、初始化、API/Web 启动，以及静态检查与构建入口。
# 关键边界：verify 仅执行静态检查与构建，不代表业务或真实模型验收通过。
.PHONY: install migrate seed api web verify verify-assets

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

verify: verify-assets
	cd api && uv run ruff check .
	cd api && uv run mypy src
	cd web && npm run lint
	cd web && npm run build

verify-assets:
	node --check docs/prototype/prototype.js
	bash -n deploy/remote-deploy.sh
