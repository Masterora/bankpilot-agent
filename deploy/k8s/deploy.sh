#!/usr/bin/env bash
# 文件职责：在远程 K3s 节点上构建、导入并部署 BankPilot。
# 主要内容：校验配置、构建镜像、导入 containerd、动态创建 Secret、应用资源并等待就绪。
# 关键边界：敏感值只从受保护的 `.env` 读取，不生成或保存含明文密钥的 YAML。
set -Eeuo pipefail

# Docker 只作为远端镜像构建器；K3s 使用自己的 containerd 运行镜像。
ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
ENV_FILE=${ENV_FILE:-"$ROOT_DIR/deploy/.env"}
KUBECTL=(sudo k3s kubectl)
API_IMAGE=bankpilot-api:0.1.0-k8s.1
WEB_IMAGE=bankpilot-web:0.1.0

if [[ ! -f "$ENV_FILE" ]]; then
  echo "missing $ENV_FILE; copy deploy/.env.example and fill all required values" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

: "${POSTGRES_DB:=bankpilot}"
: "${POSTGRES_USER:=bankpilot}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"
: "${BANKPILOT_SESSION_SECRET:?BANKPILOT_SESSION_SECRET is required}"
: "${MODEL_ID:?MODEL_ID is required}"
: "${OPENROUTER_API_KEY:?OPENROUTER_API_KEY is required}"

if (( ${#BANKPILOT_SESSION_SECRET} < 32 )); then
  echo "BANKPILOT_SESSION_SECRET must contain at least 32 characters" >&2
  exit 1
fi

echo "[1/5] build images on the remote host"
sudo docker build -t "$API_IMAGE" "$ROOT_DIR/api"
sudo docker build -t "$WEB_IMAGE" "$ROOT_DIR/web"

echo "[2/5] import images into the K3s containerd image store"
sudo docker save "$API_IMAGE" | sudo k3s ctr images import -
sudo docker save "$WEB_IMAGE" | sudo k3s ctr images import -

echo "[3/5] create the namespace and runtime Secret without writing secret YAML"
"${KUBECTL[@]}" apply -f "$ROOT_DIR/deploy/k8s/namespace.yaml"
database_url="postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}"
"${KUBECTL[@]}" -n bankpilot create secret generic bankpilot-secrets \
  --from-literal=POSTGRES_DB="$POSTGRES_DB" \
  --from-literal=POSTGRES_USER="$POSTGRES_USER" \
  --from-literal=POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
  --from-literal=BANKPILOT_DATABASE_URL="$database_url" \
  --from-literal=BANKPILOT_SESSION_SECRET="$BANKPILOT_SESSION_SECRET" \
  --from-literal=MODEL_ID="$MODEL_ID" \
  --from-literal=OPENROUTER_API_KEY="$OPENROUTER_API_KEY" \
  --dry-run=client -o yaml | "${KUBECTL[@]}" apply -f -
unset database_url

echo "[4/5] apply declarative Kubernetes resources"
"${KUBECTL[@]}" apply -k "$ROOT_DIR/deploy/k8s"

echo "[5/5] wait for database, API, and Web rollouts"
"${KUBECTL[@]}" -n bankpilot rollout status statefulset/postgres --timeout=180s
"${KUBECTL[@]}" -n bankpilot rollout status deployment/api --timeout=240s
"${KUBECTL[@]}" -n bankpilot rollout status deployment/web --timeout=180s

"${KUBECTL[@]}" -n bankpilot get pods,svc,ingress,pvc -o wide
echo "Web is exposed through the K3s Traefik Ingress on the remote host."
