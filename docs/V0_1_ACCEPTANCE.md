# v0.1 验收记录

> 日期：2026-09-03　·　结论：远程运行闭环验收通过

## 交付结果

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 本地账户与 HttpOnly Session | 通过 | 登录、登出、未认证拒绝测试 |
| 用户账单隔离 | 通过 | 跨用户 Run 返回 404 |
| OpenRouter 结构化规划 | 契约通过 | JSON Schema、Provider 策略与响应解析测试 |
| 工具白名单 | 通过 | 转账意图返回 `ACTION_NOT_ALLOWED`，未产生工具事件 |
| 本地账单查询 | 通过 | API 纵向测试返回当前用户交易 |
| Run 轮询与审计 | 通过 | 五类运行事件按序落库并返回 |
| 中断恢复 | 通过 | 启动时将非终态 Run 置为 `UNKNOWN`，不自动重做 |
| 前端 | 通过 | ESLint、Vitest、TypeScript 与 Vite 生产构建 |
| 页面布局 | 通过 | 真实浏览器检查桌面与 390px 布局，无控制台错误 |
| 远程容器部署 | 通过 | Web 由单一入口提供访问，API 与 PostgreSQL 不直接暴露到公网 |
| PostgreSQL 迁移 | 通过 | 远程 PostgreSQL 17 容器健康，Alembic 位于 `20260901_0001 (head)` |
| OpenRouter 实际调用 | 通过 | 明确模型完成结构化规划，返回 `query_transactions` |
| 远程端到端闭环 | 通过 | 登录、创建 Run、模型规划、工具查询、结果返回与审计全部完成 |

## 自动验证

```text
ruff          PASS
mypy          PASS
pytest        11 passed
eslint        PASS
vitest        2 passed
vite build    PASS
alembic       upgrade → downgrade → upgrade PASS（SQLite 隔离库）
```

## 远程验收结果

| 项目 | 状态 | 结果 |
| --- | --- | --- |
| Web 健康检查 | 通过 | 远程 Web 入口返回 HTTP 200 |
| API 就绪检查 | 通过 | `/api/v1/readyz` 返回 `ready` |
| Agent 规划 | 通过 | OpenRouter 结构化输出通过本地契约和工具白名单 |
| 账单查询 | 通过 | 临时验收账户返回预期交易，验收后数据已清理 |
| 容器状态 | 通过 | Web、API、PostgreSQL 均为 `healthy` |
| 远端 CI | 待提交后确认 | 本地工作区验证已通过，GitHub Actions 以推送结果为准 |

默认 Compose 访问通过 SSH 隧道承载。当 Web 入口配置 HTTPS 后，应将 `BANKPILOT_SESSION_COOKIE_SECURE` 设置为 `true`。
