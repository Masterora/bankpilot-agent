# verify 仅执行静态检查与构建。
.PHONY: install migrate seed api web verify verify-assets

install:
	cd api && uv sync --all-groups
	cd web && npm install

migrate:
	cd api && uv run alembic upgrade head

seed:
	cd api && uv run bankpilot seed

api:
	cd api && uv run uvicorn bankpilot.api.app:create_app --factory --no-proxy-headers --reload --port 8000

web:
	cd web && npm run dev

verify: verify-assets
	cd api && uv run ruff check .
	cd api && uv run ruff format --check src tests
	cd api && uv run mypy src
	cd web && npm run lint
	cd web && npm run format:check
	cd web && npm run build

verify-assets:
	bash -n deploy/remote-deploy.sh
