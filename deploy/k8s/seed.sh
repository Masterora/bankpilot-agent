#!/usr/bin/env bash
# 文件职责：在 K3s API Pod 中显式初始化 BankPilot 本地账户数据。
# 主要内容：校验邮箱/密码环境变量，定位 API Pod，并执行 `bankpilot seed`。
# 关键边界：凭据仅注入单次命令进程，不写入脚本、Manifest 或容器镜像。
set -Eeuo pipefail

: "${BANKPILOT_SEED_EMAIL:?set BANKPILOT_SEED_EMAIL}"
: "${BANKPILOT_SEED_PASSWORD:?set BANKPILOT_SEED_PASSWORD (at least 12 characters)}"

pod=$(sudo k3s kubectl -n bankpilot get pod -l app.kubernetes.io/name=api \
  -o jsonpath='{.items[0].metadata.name}')
sudo k3s kubectl -n bankpilot exec "$pod" -- env \
  BANKPILOT_SEED_EMAIL="$BANKPILOT_SEED_EMAIL" \
  BANKPILOT_SEED_PASSWORD="$BANKPILOT_SEED_PASSWORD" \
  uv run --no-sync bankpilot seed
