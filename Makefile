# 文件职责：提供本地开发与验证的统一命令入口。
# 主要内容：安装、迁移、初始化、API/Web 启动，以及静态、业务、交互、对话、搜索和模型验收入口。
# 关键边界：verify 不代表全部业务或真实模型通过；真实模型验收需要显式配置和外部用量授权。
.PHONY: install migrate seed api web verify verify-assets verify-business verify-interactions verify-model verify-conversations verify-search

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
	node scripts/acceptance/conversations-frontend.cjs

verify-model:
	cd api && uv run python ../scripts/acceptance/real_model.py

verify-conversations:
	cd api && uv run python ../scripts/acceptance/conversations.py

verify-search:
	cd api && uv run python ../scripts/acceptance/search.py
	node scripts/acceptance/search-frontend.cjs
