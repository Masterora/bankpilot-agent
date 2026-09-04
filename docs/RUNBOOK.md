# 运行手册

## 当前运行链路

```mermaid
sequenceDiagram
    actor U as 用户
    participant W as React Web
    participant A as FastAPI
    participant M as OpenRouter
    participant T as query_transactions
    participant P as PostgreSQL

    U->>W: 注册或登录
    W->>A: 建立 HttpOnly Session
    U->>W: 提交账单查询
    W->>A: 创建 Run 并订阅 SSE
    A->>M: 请求结构化计划
    M-->>A: 只读工具与日期参数
    A->>A: Schema、白名单和用户边界校验
    A->>T: 执行账单查询
    T->>P: 按用户与日期读取交易
    P-->>T: 交易记录
    A->>A: Decimal 统计与异常规则
    A-->>W: 结果、交易依据和审计事件
```

当前 Agent 只开放 `query_transactions`。最终产品中的导入、周期扣款、预算、报告和确认工具尚未接入当前运行链路，详见 [当前交付状态](CURRENT_STATE.md)。

## 本地开发

```bash
cp .env.example .env
cd api
uv sync --all-groups
uv run alembic upgrade head
uv run bankpilot seed
uv run uvicorn bankpilot.api.app:create_app --factory --reload --port 8000
```

另一个终端启动 Web：

```bash
cd web
npm install
npm run dev
```

打开 `http://localhost:5173`。Seed 命令交互读取邮箱和至少 12 位密码，并幂等创建本地账户、脱敏卡片和交易记录。数据库使用远程 PostgreSQL，本机不启动数据库容器。

## 必需配置

| 配置 | 要求 |
| --- | --- |
| `OPENROUTER_API_KEY` | 只配置在 API 运行环境，不得进入 Web、代码、日志或镜像 |
| `MODEL_ID` | 必须支持 `response_format=json_schema`，禁止使用自动模型 |
| `BANKPILOT_SESSION_SECRET` | 至少 32 位随机值 |
| `BANKPILOT_DATABASE_URL` | 指向 PostgreSQL；容器部署使用内部网络地址 |

OpenRouter 请求启用 `require_parameters=true` 与 `data_collection=deny`。模型只接收用户任务和规划所需上下文；原始交易由本地工具读取。模型输出必须通过 Schema、工具白名单和领域规则校验。

## 当前 API

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/api/v1/healthz` | 进程存活 |
| `GET` | `/api/v1/readyz` | 数据库就绪 |
| `POST` | `/api/v1/auth/register` | 注册用户并创建 HttpOnly Session |
| `POST` | `/api/v1/auth/login` | 创建 HttpOnly Session |
| `GET` | `/api/v1/auth/me` | 获取当前用户 |
| `POST` | `/api/v1/auth/logout` | 销毁 Session |
| `GET` | `/api/v1/cards` | 获取当前用户的脱敏卡片清单 |
| `POST` | `/api/v1/runs` | 创建账单查询 Run |
| `GET` | `/api/v1/runs/{run_id}` | 查询运行结果 |
| `GET` | `/api/v1/runs/{run_id}/events` | 订阅并续传 SSE 事件 |
| `POST` | `/api/v1/runs/{run_id}/transactions/{transaction_id}/category` | 修正交易分类并重算分析 |

路线图中的工具名称不是当前 API，不得作为已实现接口调用。

## 验证

```bash
make verify
```

API 自动测试使用隔离数据库和模型替身，不调用外部模型。发布验收必须另行执行真实 OpenRouter 请求，并分别记录模型、数据库、浏览器和远程运行结果。

服务重启会将未到终态的 Run 标记为 `UNKNOWN`，不会自动重做工具调用。仓库仅保留自动发布机制与通用容器编排；具体域名、主机、账号和凭据由 GitHub Environment 与远程环境管理。
