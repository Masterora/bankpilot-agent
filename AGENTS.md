# BankPilot repository guidance

Keep changes scoped to the user's request and preserve unrelated working-tree changes.
For local, reversible work, make reasonable assumptions and continue without asking for
approval at each step. This includes reading files, editing requested code, and running
disposable local checks that do not access production systems.

## Project boundaries

- Keep financial calculations, authorization, user isolation, and write validation in
  deterministic server code. The model may plan or explain, but it must not become the
  authority for amounts, permissions, or writes.
- Preserve the established Python stack: FastAPI, Pydantic, async SQLAlchemy, Alembic,
  asyncio, Ruff, and Mypy. Do not replace it with SQLModel, Asyncer, `ty`, or another
  framework unless the task explicitly requests a migration.
- Preserve API and CLI conventions in surrounding code. Do not perform repository-wide
  style migrations, such as converting every dependency or option to `Annotated`, as a
  side effect of a focused change.

## Read documentation only when relevant

- Read `docs/ARCHITECTURE.md` when changing service boundaries, financial semantics,
  transactions, persistence, or Agent authority.
- Read `docs/RUNBOOK.md` when changing migrations, local operations, backup, restore, or
  deployment behavior.
- Read `docs/CURRENT_STATE.md` when making release-readiness, capability, or verification
  claims.
- Do not read all project documentation before ordinary localized edits.

## Validation

Run the smallest relevant deterministic check after a change. Rerun a check only after
fixing a failure that the requested change caused. Use `make verify` for cross-cutting
changes, release preparation, or when the affected surface is uncertain. Run business,
interaction, migration, or real-model acceptance only when the change touches that
behavior; real-model checks also require explicit configuration and authorization to incur
external usage.

Local checks use disposable fixtures and have no production access. Run them, fix failures
caused by the requested change, and rerun the affected checks without asking for approval.
Do not treat a successful static check as proof of business, browser, real-model, or
production acceptance.

## Operations requiring explicit authorization

Do not deploy, push, mutate a production or shared database, run destructive migration
downgrades, delete user data or backups, rotate or expose credentials, or perform
destructive Git operations unless the user explicitly requests that operation and the
exact target is known. Keep runtime confirmations that protect sensitive input, financial
writes, imports, deletion, backup, and restore workflows.
