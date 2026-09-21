# 文件职责：提供 BankPilot 本地开发与质量检查的统一命令入口。
# 主要内容：安装、迁移、数据初始化、API/Web 启动与静态验证。
# 关键边界：`verify` 覆盖静态检查、构建与生命周期回归，业务验收需单独运行。
.PHONY: install migrate seed api web verify verify-assets verify-business verify-interactions verify-model

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
	cd api && uv run ruff check ../scripts/acceptance
	cd api && uv run mypy src
	cd api && uv run python ../scripts/acceptance/lifecycle.py
	cd web && npm run lint
	cd web && npm run build

verify-assets:
	node --check docs/prototype/prototype.js
	bash -n deploy/remote-deploy.sh

verify-business:
	cd api && uv run python ../scripts/acceptance/business.py

verify-interactions:
	node scripts/acceptance/frontend.cjs

verify-model:
	cd api && uv run python ../scripts/acceptance/real_model.py
