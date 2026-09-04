#!/usr/bin/env bash
# 文件职责：在 GitHub Actions 已连接的 Tailscale 节点上发布 BankPilot 远程源站。
# 主要内容：校验发布目标、解压临时制品、同步最新版源码、执行迁移、重建 Compose 服务并验证健康。
# 关键边界：保留远程 deploy/.env；发布包和临时目录执行后删除；脚本不读取或输出任何密钥。
set -Eeuo pipefail

: "${DEPLOY_PATH:?DEPLOY_PATH is required}"
: "${RELEASE_ARCHIVE:?RELEASE_ARCHIVE is required}"

case "$DEPLOY_PATH" in
  /*) ;;
  *) echo "DEPLOY_PATH must be absolute" >&2; exit 1 ;;
esac
if [[ "$DEPLOY_PATH" == "/" || "$DEPLOY_PATH" == "/opt" ]]; then
  echo "DEPLOY_PATH is too broad" >&2
  exit 1
fi
case "$RELEASE_ARCHIVE" in
  /tmp/bankpilot-release-*.tgz) ;;
  *) echo "unexpected release archive" >&2; exit 1 ;;
esac

staging_dir=$(mktemp -d /tmp/bankpilot-staging.XXXXXX)
cleanup() {
  rm -rf "$staging_dir"
  rm -f "$RELEASE_ARCHIVE"
}
trap cleanup EXIT

tar -xzf "$RELEASE_ARCHIVE" -C "$staging_dir"
test -f "$staging_dir/deploy/compose.yaml"
test -f "$staging_dir/api/pyproject.toml"
test -f "$staging_dir/web/package.json"
test -f "$DEPLOY_PATH/deploy/.env"

# 仅保留受保护的生产配置；源码目录始终与 main 的最新提交一致。
sudo rsync -a --delete --exclude='deploy/.env' "$staging_dir/" "$DEPLOY_PATH/"

cd "$DEPLOY_PATH/deploy"
sudo docker compose --env-file .env build api web
# 远程脚本由 SSH 标准输入传入；迁移容器不得继续读取并吞掉后续发布命令。
sudo docker compose --env-file .env run --rm --no-TTY --interactive=false \
  api uv run alembic upgrade head
# Compose 在启用镜像 provenance 时可能无法仅凭镜像摘要识别新构建；发布必须重建运行容器。
sudo docker compose --env-file .env up -d --remove-orphans --force-recreate api web

sudo docker compose --env-file .env exec -T api \
  python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/readyz', timeout=5)"
sudo docker compose --env-file .env exec -T web \
  wget -q -O - http://127.0.0.1:8080/healthz >/dev/null
sudo docker compose --env-file .env ps api web postgres
