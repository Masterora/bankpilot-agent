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

`make api` 和 API 容器只启动服务，不自动迁移。对明确授权的目标单独执行 `make migrate`，再启动 API。数据库结构变化先在隔离 PostgreSQL 验证升降级，再迁移业务库；当前工作树结构版本是 `20261009_0022`（34 张表，由 `SCHEMA_REVISION` 声明）；共享业务库本轮未升级。

```bash
cd api
uv run alembic upgrade head
uv run alembic check
```

本地配置来自 `.env`；CI 使用 Workflow 和临时 PostgreSQL；线上使用 GitHub Environment 与远程 `deploy/.env`。`BANKPILOT_API_ORIGIN` 设置本地代理目标，`PUBLIC_WEB_ORIGIN` 设置线上允许的页面来源。

`BANKPILOT_TIMEZONE` 默认 `Asia/Shanghai`，接受 IANA 时区名称，用于 Agent 理解“今天”“本月”等相对日期。审计时间保存为 UTC，页面统一显示 UTC+8；该配置不改变页面显示时区或已导入交易的账务日期。

`WEB_BIND_IP` 使用远程 Tailscale 地址。私网 HTTP 配置 `BANKPILOT_SESSION_COOKIE_SECURE=false`，HTTPS 配置为 `true`。模型端启用 `require_parameters=true` 与 `data_collection=deny`。

`BANKPILOT_RECURRING_DISCOVERY_ENABLED` 默认 `false`；服务端同时控制发现接口与页面入口。仅在 R6 验收环境明确设为 `true` 做受控检查，真实样本与完整验收达到 [真实样本启用门槛](ROADMAP.md#r6-发现验收与扩展)前不要在一般用户环境开启。修改后需重启 API；Web 从服务端读取可用状态，无需单独构建开关。

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
uv run bankpilot restore-prepare --directory /secure/backups/bankpilot-20260915 --expected-db bankpilot_recovery --apply --clear-assistant-history
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

## 会话历史与恢复降级

必须同批升级前后端。旧 `POST /api/v1/assistant/chat` 返回 `assistant_protocol_upgrade`，
刷新后使用协议版本 5 的 `/assistant/turns`，助手接口携带 `X-Assistant-Protocol: 5`，新结果写版本 4；已有版本 3 的已完成结果仍可读取，其他旧版本结果不可用。
只在明确授权后对共享业务库执行迁移。

集中配置 `ASSISTANT_MAX_CONVERSATIONS=100`、`ASSISTANT_MAX_TURNS=200`、
`ASSISTANT_MAX_RESULT_CHARS=400000`、`ASSISTANT_CONTEXT_CHARS=24000`。
处理截止从数据库受理时间起算 90 秒；每个实例启动时及每 15 秒扫描到期记录，读取状态也收敛。
数据库不可用时不承诺扫描时限，恢复后继续；不重跑模型。

`restore-prepare` 预览现在同时显示目标库名、聊天和轮次数量、保留的业务范围。
执行需要 `--apply --clear-assistant-history` 并在终端确认。清除恢复库的**全部**聊天内容、
取消待确认提案和清除登录会话；保留无内容创建标识，拒绝旧客户端重建已清理会话。
账本、预算、固定支出、月报和已执行回执保留。未完成清理及复核前不得开放恢复环境。
此降级会同时清除原本未删除的聊天；旧备份本体不改写，恢复后的账本 RPO 仍由备份时间决定。

仓库内固定验收脚本及对应 Makefile 入口已于 2026-09-21 删除。后续会话与恢复验收仍须使用显式指定的隔离库，不得使用默认业务库配置。

## 发布与验证

当前工作树迁移为 `20261009_0022`，包含 34 张表；共享环境本轮未迁移或发布。会话请求使用协议 5，保存请求缺上下文版本会被拒绝；分类与核查保存必须携带账本修订号。前后端须同批升级，旧页面需刷新。部署须另行授权。

运行 `make verify` 执行静态检查与构建。搜索、会话、业务和交互自动回归入口已删除；发布前仍需在隔离环境另行验证这些行为，包括实际 dump/restore、准备清理幂等和迁移往返。

备份结构校验版本已同步。旧备份由与其迁移配套的应用先验证，再按升级流程处理，不跳过结构校验。删除/恢复清理包括 `search_context`，墓碑不残留商户文本。模型验证边界见 [模型记录](MODEL_VALIDATION.md)。

## R5 待办状态运维

R5 增加 `attention_states`、`attention_preferences` 与 `attention_operations`，前后端必须同批升级。升级不预生成历史待办；用户首次操作后才保存单项状态。回执当前不自动清理，容量规划应同时观察三张表的行数。恢复准备保留状态、偏好和回执，已过期稍后项目由读取投影为未读，不运行后台任务。

CI 隔离迁移门禁为 `upgrade head → alembic check → downgrade 20260906_0006 → upgrade head → alembic check`。迁移、备份、发布和回滚仍需单独授权，不得在共享库执行降级验收。

## R7 站内通知

`BANKPILOT_NOTIFICATIONS_ENABLED=false` 为默认值，同时关闭事件写入、消费者和 UI 入口。只有 [R7 本地记录](R7_ACCEPTANCE.md) 的发布门槛通过后才受控启用；本轮未迁移共享库或发布。发布前须迁移到当前 head（0020），前后端同批部署。

每次重新启用更换 `BANKPILOT_NOTIFICATION_EPOCH`（1—64 字符），全部 API 实例使用同一开关及 epoch。共享租约拒绝混合安全限额、会话密钥、通知开关或 epoch；每 15 秒续租，90 秒失效，单次注册/续租最多等待 3 秒。失败时拒绝数据库请求并暂停后台执行者，持续重试；只有重新取得有效配置租约才恢复请求及后台任务，冲突配置不会恢复为可用。修改这些配置须先停止所有旧实例。无事件基线在用户锁内完成；容量失败用户五分钟后重试，只阻止该用户产生事件，不阻断其他已完成基线的用户。不得从截断事实建立基线。开关关闭不重置排程或抑制状态，也不删除历史通知；重启启用时旧未完成事件被抑制，不补发停用期间转换。

消费者每五秒查找待处理工作，领取租约 90 秒，单次执行（含锁等待和提交）最多 45 秒，并受剩余租约时间约束，事件最多五次尝试；后台不调用模型。排程覆盖本地业务午夜与最早稍后截止，扫描迟到超过 60 秒时界面显示“待同步”。短暂失败退避，失败终态由运维检查，不自动重放旧事件。

观察 notification_outbox 的 pending/running/failed 数量及最旧 occurred_at、notification_schedules 的 next_check_at 延迟；结合 notification_scan_completed / notification_event_completed / notification_processing_failed JSON 作业日志及 HTTP 耗时定位。日志通过 uvicorn.error 输出；扫描作业使用领取令牌标识，不记录用户身份、交易内容或 SQL 文本。未抑制通知超过 1,000 条时计数不完整，首版不清理去重身份；规模扩大前另做容量与保留策略验收。

备份自动包含通知表和安全限额表。先在隔离恢复库执行原始 32 表核对，prepare 预览会列出待抑制事件、待重置排程和待清理安全租约数量；原有 --apply、--clear-assistant-history 及终端确认仍保留。prepare 抑制 pending/running/failed、清除领取令牌并要求重新建立基线；保留已创建通知、已查看时间、业务处理状态和累计安全额度。重复准备仍以完整证据收据判定。不得在共享业务库执行迁移降级或恢复测试。

## 安全限额与客户端身份

迁移 0019 增加共享计数和租约两表；必须先迁移明确授权的数据库，再同批更新 API/Web。私有 API 先通过 `/api/v1/auth/me` 获取身份，再携带 `X-BankPilot-User`；SSE 使用 `expected_user_id` 查询参数。缺失或与 Cookie 所属用户不一致返回 409，旧页面须刷新。改密同时提交 `current_password` 和 `new_password`，成功后轮换当前 Cookie 并撤销其他会话。

认证按每分钟全局、连接来源、账户限额在哈希前受理；默认分别为 60、20、8，密码计算并发为 4。启动命令关闭代理头信任，反向代理后的来源可能共享同一限额，不以客户端自行声明的 IP 放宽限制。模型默认每用户/全局活跃工作 2/8、每日工作 40/400、HTTP 尝试 240/2400、保守 token 预留 200 万/2000 万；重试也计入限额，失败不退还预留。日窗口为 UTC 固定日，重启不清零。token 预留不是供应商账单金额，仍需设置供应商账户消费上限。SSE 每用户/全局连接默认 2/16，最长 120 秒，轮询复核会话并释放短连接。

具体环境变量及默认值见 `.env.example`，Compose 显式传递通知、助手和安全限额；`--env-file` 本身只提供插值，不会自动注入容器。恢复准备清理没有存活拥有者的安全租约，保留共享用量计数；只有隔离的恢复目标可执行。


## 账户数据与查询订阅运维

0020 仅扩展持久会话字段及索引，表数仍为 31；共享环境迁移和部署仍须授权。查询订阅与 R5 站内通知共用通知开关和 epoch，关闭时不扫描；重新启用更换 epoch，订阅第一次完整检查建立新基线，不补发停用期间变化。默认未启用。

扫描每五秒最多检查 20 项，单项间隔至少 60 秒；检查超出 120 秒、容量/归属异常会使收件箱计数显示待同步。观察 `assistant_conversations.search_checked_at/search_check_error` 与通用扫描不可用日志，不在日志打印查询文本或用户标识。不要绕过每用户 20 项及完整搜索容量限制；大规模启用仍需代表性性能验收。

个人 JSON 导出限 50,000 行、20 MiB、30 秒，每用户/全局并发 1/2；超限用户可使用既有账本、月报分批导出。导出不替代数据库备份。注销只清理在线数据库，已生成的备份遵循现有独立保留政策；不自动删除备份。恢复准备清理所有会话查询及订阅身份，与聊天清除确认一起执行；恢复旧备份可能包含已注销用户，不得直接开放未核对的恢复环境。


## 预算结转运维

升级 `0021` 增加冻结回执表，不修改已有预算或已发布迁移。前后端同批升级后，预算页面可读取预览并显式确认；没有后台自动结转开关。目标月份一次确认后只能读取回执，后续额度调整使用原预算编辑流程。

生产回滚不得盲目降级 `0021`：降级只删除回执，不还原已经增加的预算额度；再次升级会丢失去重证据，可能允许再次结转。应用回退应保留数据库与回执，并暂停结转入口；任何业务额度恢复须按明确目标另行确认，不能凭迁移降级推断金额已恢复。本轮升降级仅在空的隔离迁移库执行，带数据业务库只验证备份还原。


## R8 账期与暂停历史升级

0022 增加账期声明、状态边界及历史起点，旧计划状态和版本保留，历史起点为未知。前后端同批升级；旧客户端状态请求缺日期按当天处理。共享环境本轮未迁移，新页面不得对未升级 API 使用。

月结只记录用户声明，不冻结补录。导入、撤销、分类或关系等账本修订使已确认标记失效；重新打开或重新核对通过页面明确确认，不直接改数据库。

0022 降级会删除两项功能数据，且主记录保留的是旧／初始状态基线，降级后运行旧应用可能把已经暂停的计划按基线重新展示。因此带数据环境应保留结构和历史，应用回退前关闭相关入口并另行设计兼容方案；不能盲目 downgrade。0021 备份须用对应版本应用恢复再按正式流程升级，不绕过恢复证据的严格结构核对。34 表备份还原和隔离迁移结果见 [R8 本地验收](R8_ACCEPTANCE.md)。
