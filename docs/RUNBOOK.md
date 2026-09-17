# 运行手册

默认启动命令将 React 与 FastAPI 分别绑定到 5173 和 8000 端口，Web 通过 `/api` 代理访问 API。共享业务环境的数据库部署在远程主机，本地通过 Tailscale SSH 隧道连接；线上 API 经容器内部网络连接同一数据库。实际连接目标以运行环境配置为准。

使用共享业务库配置时，本地与线上共享数据。测试应显式指定独立数据库并使用临时账户，不在共享库执行 seed。2026-09-15 至 09-16 的隔离验收使用 Web 5174、API 18001、PostgreSQL 55439；这些是当次验收端口，不代表服务当前正在运行。

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

`make api` 会执行 `alembic upgrade head`。数据库结构变化先在隔离 PostgreSQL 验证升降级，再迁移业务库；当前代码结构版本是 `20260916_0012`（由 `api/src/bankpilot/db/base.py` 的 `SCHEMA_REVISION` 声明，与迁移 head 一致）；共享业务库是否升级需现场核对。

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

## 月报任务

每个 API 实例启动一个月报消费者，每用户最多两项等待或运行中的报告。单次执行最多 45 秒，领取租约 90 秒，瞬时错误最多尝试三次，期间超限直接失败。进程中断后恢复过期任务；旧实例结果不能覆盖重新领取或已删除的任务。删除报告清除快照，保留不含交易证据的幂等墓碑；清除用户数据时外键级联删除对应报告。

迁移回退会删除月报表及其证据；正式升级前应备份，生产回滚不应盲目执行降级。本轮只在隔离库验证迁移，不代表已完成生产备份恢复演练。

[系统架构](ARCHITECTURE.md) · [交付与验证](CURRENT_STATE.md)

## 导入协议与恢复

正式 POST /api/v1/imports 必须携带 UUID idempotency_key；预览无需 key。首次创建批次返回 201，重放返回 200，同 key 不同输入 409；行错误创建 REJECTED 报告，不能仅凭 201 判断入账。GET /api/v1/imports/by-key/{key} 查询当前用户的原操作；404 只表示此刻未见已提交结果。网络失败保留同 key，禁止自动换 key。

部署必须同批发布前后端并要求旧页面刷新；旧页面缺 key 被明确拒绝。迁移只新增字段，历史批次不填造新统计。回退应用必须继续支持幂等协议，否则先暂停导入；不通过删字段回滚已提交事实。

## 离线备份与还原

维护机器需要与服务端匹配的 PostgreSQL 17 pg_dump/pg_restore，以及本项目 uv 环境。命令不启动 API 或消费者；无需给应用增加消费者开关。数据库 URL 从明确的环境变量读取，不在命令参数中放口令；恢复不能默认使用业务库配置。

在已经配置好加密存储的目录创建新备份（父目录须存在）：

```bash
cd api
uv run bankpilot backup-db --directory /secure/backups/bankpilot-20260915 --application-commit <应用提交>
```

运行前设置 BANKPILOT_BACKUP_DATABASE_URL。命令输出行摘要清单和 PostgreSQL custom 格式文件；文件 0600、目录 0700。完成标志是 manifest.json，失败目录不能当作成功备份。加密由存储层提供，命令不配置磁盘加密；异机复制和每日调度需在运行环境配置。当前没有自动删除旧备份，7 日/4 周保留策略仍是运维候选，不能在未验证新备份时清理。

还原前创建一个不同名称的空数据库，为 BANKPILOT_RESTORE_DATABASE_URL 配置只允许访问恢复库的凭据；禁止 API、消费者或其他客户端连接恢复库：

```bash
uv run bankpilot restore-db --directory /secure/backups/bankpilot-20260915 --expected-db bankpilot_recovery
uv run bankpilot restore-check --directory /secure/backups/bankpilot-20260915 --expected-db bankpilot_recovery
uv run bankpilot restore-prepare --directory /secure/backups/bankpilot-20260915 --expected-db bankpilot_recovery
uv run bankpilot restore-prepare --directory /secure/backups/bankpilot-20260915 --expected-db bankpilot_recovery --apply
```

restore-db 校验备份大小/摘要，拒绝同源库名、非空库或存在其他客户端的目标，事务化还原后核对完整证据。restore-check 是只读操作，比较所有表有序摘要、列类型/空值/默认值/标识列/排序规则、约束条件与验证状态、索引定义、币种总额与快照模型。原始核对必须先于 prepare。

prepare 默认显示将处理的任务数量；--apply 失效运行中报告令牌，剩余次数可用则排队，否则失败；未终结 Agent 进入 UNKNOWN，并清除旧会话。准备前核对原始证据，提交前在受限备份目录保存预期结果收据；重复 prepare 仅在完整数据库仍匹配收据时返回零变更。prepare 后 restore-check 对照原始备份会发现预期差异，使用重复 prepare 验证准备后的状态。

恢复结构证据使用版本 2 清单。CHECK 条件以 PostgreSQL `EXPLAIN (VERBOSE, FORMAT JSON)` 的输出表达式进行规范化；不使用 ANALYZE，不执行表扫描，也不比较成本与行数估计。隐式数组转换的还原差异由 PostgreSQL 自身规范化，不能省略条件。结构摘要绑定 PostgreSQL 主版本；跨主版本迁移需独立验收。旧的版本 1 演练清单缺少完整结构证据，命令明确拒绝，需重新生成版本 2 备份；不提供弱校验回退。

离线命令的 URL 必须包含主机、用户与库名。运行环境若设置 PGHOST、PGHOSTADDR、PGPORT、PGDATABASE、PGUSER、PGPASSWORD、PGSERVICE、PGSERVICEFILE 或 PGPASSFILE，命令在连接及创建备份目录前直接拒绝；先清除这些覆盖项，再使用 BANKPILOT_BACKUP_DATABASE_URL / BANKPILOT_RESTORE_DATABASE_URL。约束列身份按有序列名核对，不依赖删除列后可能变化的物理编号；迁移回退再升级的库也必须通过逻辑还原验收。

完成后再使用恢复库配置启动单个 API 进程（一个 worker、关闭 reload），验证原报告导出、等待任务收敛和临时登录。此时不能继续对已经产生新业务写入的库重复 prepare。生产切换还需单独核对隔离、停止旧写入方和恢复目标，不凭小规模演练宣称达到 RPO/RTO。

## 查询耗时定位

HTTP 响应提供 X-Request-ID 与 Server-Timing（db、connection、parse，毫秒），服务端记录路由模板、状态、SQL 次数及响应发送耗时；不记录 SQL 参数和账单内容。后台运行使用独立 job_id。SQL 时间包含驱动/网络往返，需要查询计划才能判断索引问题。

本地数据库与 SSH/Tailscale 链路分开测量；连接获取预算或网络延迟不能当成 SQL 执行慢。readyz 实际查询数据库，总预算 3 秒，断连/超时返回 503；healthz 无数据库依赖。

助手请求的服务端总预算为 90 秒，Web 代理读取超时为 120 秒；调整时须保留代理余量。部署必须同时更新 API 和 Web，不能仅以本地 Vite 请求成功代替代理链路验收。
