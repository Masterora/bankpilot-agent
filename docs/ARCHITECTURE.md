# 系统架构

系统以三个约束为核心：账务结果可复算、模型行为受控制、外部来源可替换。交易账本是唯一事实来源，Agent 不能绕过领域服务接触数据库。

## 总体结构

```mermaid
flowchart TB
    subgraph WEB[React Web]
        UI[认证 · 导入 · 账本 · Agent · 审计]
    end

    subgraph APP[FastAPI Application]
        HTTP[API 契约与会话]
        USECASE[业务用例]
        AGENT[Agent 编排]
    end

    subgraph CORE[Domain Core]
        PARSER[来源解析器]
        LEDGER[账户与交易账本]
        RULES[分类 · 核查 · 交易关系]
        TOOLS[白名单工具]
    end

    subgraph INFRA[Infrastructure]
        DB[(PostgreSQL)]
        GATEWAY[Model Gateway]
        OPENROUTER[OpenRouter]
    end

    UI --> HTTP
    HTTP --> USECASE --> PARSER
    USECASE --> LEDGER --> RULES
    HTTP --> AGENT --> TOOLS --> LEDGER
    AGENT --> GATEWAY --> OPENROUTER
    USECASE --> DB
    AGENT --> DB
```

文件格式变化被限制在来源适配器，模型供应商变化被限制在 Model Gateway。金额、权限、事务和用户归属始终位于确定性核心中。分析结果只能形成独立记录或快照，不能覆盖原始交易。

## 数据流

```mermaid
sequenceDiagram
    actor U as 用户
    participant W as Web
    participant API as FastAPI
    participant D as Domain
    participant DB as PostgreSQL
    participant M as Model Gateway

    U->>W: 选择账单并确认账户
    W->>API: 解码、识别与预览
    API->>D: 解析并校验全部交易
    D-->>API: 预览、排除项与错误
    API-->>W: 返回预览结果
    U->>W: 确认导入
    W->>API: 提交同一解析契约
    API->>DB: 原子写入批次与交易
    U->>W: 查询或核对关系
    W->>API: 当前用户任务
    API->>M: 请求结构化规划
    M-->>API: 工具与参数
    API->>D: 执行白名单查询与计算
    API->>DB: 保存结果快照与事件
    API-->>W: 返回证据与结果
```

预览和导入复用同一解析器。原文件只在内存中解码，交易记录保留来源批次和行号。分类修正不改变原始字段，交易关系不删除流水。

## 交易关系模型

```mermaid
flowchart LR
    RAW[原始流水] --> CANDIDATE{候选关系}
    CANDIDATE --> DUP[重复<br/>跨批次、等额、相差不超过 1 天]
    CANDIDATE --> TRANSFER[本人转账<br/>跨账户、等额收支、相差不超过 3 天]
    CANDIDATE --> REFUND[退款<br/>支出后 90 天内、累计不超原金额]
    DUP --> CONFIRM{用户确认}
    TRANSFER --> CONFIRM
    REFUND --> CONFIRM
    CONFIRM -->|确认| ADJUST[生成调整统计]
    CONFIRM -->|排除 / 撤销| RAW
```

候选只缩小人工核对范围。无论自动建议还是手动配对，服务端都会重新检查事实约束、用户归属和并发版本。

## Agent 控制面

```mermaid
flowchart LR
    ASK[用户问题] --> PLAN[模型生成结构化计划]
    PLAN --> ALLOW{工具与参数白名单}
    ALLOW -->|拒绝| SAFE[返回安全错误]
    ALLOW -->|通过| EXEC[领域服务执行]
    EXEC --> EVIDENCE[交易证据与确定性结果]
    EVIDENCE --> ANSWER[组织回答并保存快照]
```

模型可以理解日期、识别核查意图并选择工具，但不能指定用户身份、访问数据库、修改金额或覆盖权限。当前 Agent 只开放账本查询；模型不可用时，导入、账本、分类和导出仍可运行。

## 代码边界

```text
web/src/app          页面注册、导航、跨页面状态
web/src/features     独立产品功能界面

api/.../api          认证、请求校验、响应契约
api/.../services     用例事务、跨领域编排
api/.../domain       解析、金额、分类、关系、核查规则
api/.../adapters     模型与外部能力适配
api/.../db           用户归属、关系与持久化
```

用户身份只从服务端 Session 获取；密钥不得进入代码、Web、日志或镜像；数据库结构只通过 Alembic 修改；整批导入遇到有效性错误即停止写入；候选关系和核查信号不会自动改变金额；CI 只能使用独立数据库。

[运行手册](RUNBOOK.md) · [当前交付状态](CURRENT_STATE.md)
