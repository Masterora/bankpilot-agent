# 运行手册

本地 React 与 FastAPI 分别运行在 5173 和 8000 端口，Web 通过 `/api` 代理访问 API。业务数据库部署在远程主机，本地通过 Tailscale SSH 隧道连接。线上 API 经容器内部网络连接同一数据库。

本地与线上共享业务数据。测试使用独立数据库和临时账户，不在共享库执行 seed。

## 本地启动

首次准备环境；已有 `.env` 时保留其中配置：

```bash
test -f .env || cp .env.example .env
chmod 600 .env
make install
```

在 `.env` 填写 `BANKPILOT_DATABASE_URL`、`BANKPILOT_SESSION_SECRET`、`MODEL_ID` 与 `OPENROUTER_API_KEY`。Session Secret 至少 32 位，模型使用支持 JSON Schema 的明确型号。真实配置不提交 Git。

建立并保持数据库隧道：

```bash
ssh -N -L 127.0.0.1:55433:127.0.0.1:55433 \
  -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
  -i <ssh-key> <user>@<tailscale-host>
```

分别在两个终端启动：

```bash
make api
```

```bash
make web
```

页面地址是 [localhost:5173](http://127.0.0.1:5173)。`/api/v1/healthz` 检查 API 存活，`/api/v1/readyz` 检查数据库就绪；两个接口可通过 Web 代理或本地 API 访问。连接失败先检查 Tailscale、SSH 验证和隧道进程。

## 数据与配置

`make api` 会执行 `alembic upgrade head`。数据库结构变化先在隔离 PostgreSQL 验证升降级，再迁移业务库；当前迁移头是 `20260906_0006`。

```bash
cd api
uv run alembic upgrade head
uv run alembic check
```

本地配置来自 `.env`；CI 使用 Workflow 和临时 PostgreSQL；线上使用 GitHub Environment 与远程 `deploy/.env`。`BANKPILOT_API_ORIGIN` 设置本地代理目标，`PUBLIC_WEB_ORIGIN` 设置线上允许的页面来源。

`BANKPILOT_TIMEZONE` 默认 `Asia/Shanghai`，接受 IANA 时区名称，用于 Agent 理解“今天”“本月”等相对日期。审计时间保存为 UTC，页面统一显示 UTC+8；该配置不改变页面显示时区或已导入交易的账务日期。

`WEB_BIND_IP` 使用远程 Tailscale 地址。私网 HTTP 配置 `BANKPILOT_SESSION_COOKIE_SECURE=false`，HTTPS 配置为 `true`。模型端启用 `require_parameters=true` 与 `data_collection=deny`。

## 验证与发布

```bash
make verify
```

该命令覆盖 Ruff、Mypy、ESLint、TypeScript 与 Web 构建。业务验收另行验证注册登录、导入拒绝与去重、分类、跨期关系、候选截断、Agent 调整统计、证据快照和用户隔离。运行快照在关系撤销或重新确认后应保持原值，新查询应反映最新结果。

Agent 在单次可重复读事务中读取核查数据，超过工作区上限会失败并要求缩小期间。运行每 15 秒续约，超过 2 分钟未更新收敛为 `UNKNOWN`，不自动重做工具调用。

CI 的静态检查、构建和隔离迁移通过后，发布仍须验证 API/Web 版本一致、迁移成功、Cookie 正确、页面登录和真实模型请求。主机、域名与凭据只保存在运行环境。

[系统架构](ARCHITECTURE.md) · [交付与验证](CURRENT_STATE.md)
