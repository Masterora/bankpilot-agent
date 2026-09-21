---
name: bankpilot-fastapi
description: Change BankPilot FastAPI routes, dependencies, response schemas, or streaming endpoints. Do not use for generic Pydantic, database-only, CLI, or frontend work.
---

# BankPilot FastAPI

Use this skill only for work that changes BankPilot's HTTP interface or FastAPI-specific
behavior.

## Repository conventions

- Keep route handlers thin. Put financial and application behavior in the existing domain,
  service, and repository layers.
- Use the established async SQLAlchemy stack. Do not introduce SQLModel or replace asyncio,
  Mypy, or the repository's other selected tools.
- Preserve the style of nearby endpoint parameters and dependencies. For new or
  substantially changed signatures, use `Annotated` when it improves clarity or reuse;
  do not migrate unaffected endpoints solely for consistency.
- Create a dependency alias only when it is reused or carries a meaningful contract.
- Keep public request and response schemas explicit, and do not expose ORM records or
  sensitive internal fields directly.
- Avoid blocking work inside async handlers. Follow existing service boundaries for
  transactions and commits.
- The React application is served separately. Do not introduce `app.frontend()` or change
  frontend hosting unless the task explicitly changes deployment architecture.

## Context and validation

Read `docs/ARCHITECTURE.md` only when the change affects financial semantics, transaction
ownership, persistence, or Agent authority. Read `docs/RUNBOOK.md` only for operational or
deployment behavior. Follow the validation policy in the repository `AGENTS.md`; ordinary
route edits do not require every acceptance suite.
