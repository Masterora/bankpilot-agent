---
name: bankpilot-typer
description: Change BankPilot Typer commands, arguments, options, prompts, or Typer-specific behavior. Do not use for generic Python services or shell scripts.
---

# BankPilot Typer CLI

Use this skill only for the Typer application in `api/src/bankpilot/cli.py` and directly
related command behavior.

## Repository conventions

- Extend the existing explicit `typer.Typer` application; do not replace it with
  `typer.run` or another CLI framework during a focused change.
- Prefer `Annotated` for new or substantially changed options when it makes the declaration
  clearer. Preserve valid untouched declarations instead of performing a CLI-wide style
  migration.
- Preserve hidden input and runtime confirmation for passwords and destructive operations.
  These are product safety controls, not reasons for the coding agent to request approval
  for ordinary local edits or tests.
- Keep credentials and database URLs in the established environment variables. Do not add
  secrets to command arguments, output, examples, or tracked files.
- Preserve the existing async SQLAlchemy and asyncio implementation. Do not substitute
  SQLModel, Asyncer, or unrelated tooling.
- Backup and restore commands must retain target validation, safe defaults, and explicit
  opt-in for mutations.

## Context and validation

Read `docs/RUNBOOK.md` only when changing backup, restore, migration, deployment, or other
operational commands. Follow the validation policy in the repository `AGENTS.md`; a local
CLI edit does not require real-model or browser acceptance.
