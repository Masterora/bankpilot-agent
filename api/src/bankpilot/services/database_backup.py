"""文件职责：通过显式连接执行一致性逻辑备份、空库还原及验证。
关键边界：口令仅经子进程环境传递；新目录写入，完整校验后才发布清单，不清理旧备份。
"""

import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from bankpilot.db.session import create_engine, create_session_factory
from bankpilot.services.restore_validation import (
    DatabaseEvidence,
    database_evidence,
    database_identity,
    prepare_restored_tasks,
)


class BackupManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = 2
    created_at: datetime
    source: dict[str, str]
    postgres_version: str
    application_commit: str
    sha256: str
    size: int
    evidence: DatabaseEvidence


def pg_environment(url: str) -> dict[str, str]:
    parsed = make_url(url)
    if (
        parsed.drivername != "postgresql+asyncpg"
        or not parsed.host
        or not parsed.database
        or not parsed.username
    ):
        raise ValueError("Explicit postgresql+asyncpg host, user and database are required")
    if parsed.query:
        raise ValueError("Operation database URL query options are unsupported")
    # asyncpg 与 libpq 对服务文件、hostaddr 和缺省凭据的解释不同。
    # 在任何连接之前拒绝第二套目标配置，不允许校验库与实际还原库分离。
    connection_variables = {
        "PGHOST", "PGHOSTADDR", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD",
        "PGSERVICE", "PGSERVICEFILE", "PGPASSFILE",
    }
    if connection_variables.intersection(os.environ):
        raise ValueError("Remove PG connection overrides; use the explicit operation URL")
    environment = dict(os.environ)
    environment.update(
        PGHOST=parsed.host,
        PGPORT=str(parsed.port or 5432),
        PGDATABASE=parsed.database,
        PGUSER=parsed.username,
        PGPASSWORD=parsed.password or "",
    )
    return environment


async def pg_command(command: list[str], url: str) -> None:
    process = await asyncio.create_subprocess_exec(
        *command,
        env=pg_environment(url),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        async with asyncio.timeout(3600):
            _, _ = await process.communicate()
    except BaseException:
        process.kill()
        await process.wait()
        raise
    if process.returncode:
        # pg 输出可能包含标识符/数据；不传播到应用日志。
        raise ValueError(f"{command[0]} failed; backup/restore is incomplete")


def file_digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


async def backup_database(url: str, directory: Path, commit: str) -> dict[str, str | int]:
    pg_environment(url)
    await asyncio.to_thread(directory.mkdir, mode=0o700, parents=False, exist_ok=False)
    engine = create_engine(url)
    dump = directory / "database.dump"
    try:
        async with create_session_factory(engine)() as session:
            await session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            await session.execute(text("SET TRANSACTION READ ONLY"))
            source = await database_identity(session)
            snapshot = str(await session.scalar(text("SELECT pg_export_snapshot()")))
            evidence = await database_evidence(session)
            version = str(await session.scalar(text("SHOW server_version")))
            await pg_command(
                [
                    "pg_dump",
                    "--format=custom",
                    "--no-owner",
                    "--no-privileges",
                    "--snapshot",
                    snapshot,
                    "--file",
                    str(dump),
                ],
                url,
            )
            dump.chmod(0o600)
            await pg_command(["pg_restore", "--list", str(dump)], url)
            manifest = BackupManifest(
                created_at=datetime.now(UTC),
                source=source,
                postgres_version=version,
                application_commit=commit,
                sha256=file_digest(dump),
                size=dump.stat().st_size,
                evidence=evidence,
            )
            manifest_path = directory / "manifest.json"
            with manifest_path.open("x") as stream:
                stream.write(manifest.model_dump_json(indent=2))
            manifest_path.chmod(0o600)
            return {
                "tables": len(evidence.counts),
                "bytes": manifest.size,
                "sha256": manifest.sha256,
            }
    finally:
        await engine.dispose()


def read_manifest(directory: Path) -> BackupManifest:
    manifest = BackupManifest.model_validate_json((directory / "manifest.json").read_text())
    if manifest.version != 2:
        raise ValueError("Unsupported backup manifest version")
    dump = directory / "database.dump"
    if dump.stat().st_size != manifest.size or file_digest(dump) != manifest.sha256:
        raise ValueError("Backup size or checksum mismatch")
    return manifest


async def validate_target(
    session: AsyncSession,
    expected_db: str,
    manifest: BackupManifest,
) -> None:
    identity = await database_identity(session)
    if identity["database"] != expected_db:
        raise ValueError("Actual database does not match --expected-db")
    # 强制不同库名，避免隧道/别名导致源库识别绕过。
    if identity["database"] == manifest.source["database"]:
        raise ValueError("Recovery database must have a different name from the source")
    connected = int(
        await session.scalar(
            text(
                "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                "AND pid <> pg_backend_pid() AND backend_type='client backend'"
            )
        )
        or 0
    )
    if connected:
        raise ValueError("Recovery database has other clients; stop its consumers first")


async def restore_database(url: str, directory: Path, expected_db: str) -> dict[str, int]:
    pg_environment(url)
    manifest = read_manifest(directory)
    engine = create_engine(url)
    try:
        async with create_session_factory(engine)() as session:
            await validate_target(session, expected_db, manifest)
            tables = await session.scalar(
                text(
                    "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname NOT IN ('pg_catalog','information_schema') "
                    "AND n.nspname NOT LIKE 'pg_toast%' AND c.relkind IN ('r','p','v','m','S')"
                )
            )
            if tables:
                raise ValueError("Restore requires an empty database")
        await pg_command(
            [
                "pg_restore",
                "--exit-on-error",
                "--single-transaction",
                "--no-owner",
                "--no-privileges",
                "--dbname",
                expected_db,
                str(directory / "database.dump"),
            ],
            url,
        )
    finally:
        await engine.dispose()
    return await check_restored(url, directory, expected_db)


async def check_restored(
    url: str,
    directory: Path,
    expected_db: str,
    *,
    prepare: bool = False,
    apply: bool = False,
) -> dict[str, int]:
    pg_environment(url)
    manifest = read_manifest(directory)
    engine = create_engine(url)
    try:
        async with create_session_factory(engine)() as session:
            await session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            if not (prepare and apply):
                await session.execute(text("SET TRANSACTION READ ONLY"))
            await validate_target(session, expected_db, manifest)
            evidence = await database_evidence(session)
            receipt_path = directory / (
                "prepared-" + hashlib.sha256(expected_db.encode()).hexdigest()[:16] + ".json"
            )
            if prepare and receipt_path.exists():
                receipt = json.loads(receipt_path.read_text())
                if (
                    receipt["backup_sha256"] == manifest.sha256
                    and receipt["database"] == expected_db
                    and DatabaseEvidence.model_validate(receipt["evidence"]) == evidence
                ):
                    return {"reports": 0, "runs": 0}
            if evidence != manifest.evidence:
                raise ValueError("Restored database differs from backup evidence")
            if prepare:
                # dry-run 不执行 FOR UPDATE；显式 apply 才锁行。
                if not apply:
                    reports = int(
                        await session.scalar(
                            text("SELECT count(*) FROM monthly_reports WHERE status='RUNNING'")
                        )
                        or 0
                    )
                    runs = int(
                        await session.scalar(
                            text(
                                "SELECT count(*) FROM runs "
                                "WHERE status IN ('CREATED','PLANNING','EXECUTING')"
                            )
                        )
                        or 0
                    )
                    return {"reports": reports, "runs": runs}
                result = await prepare_restored_tasks(session)
                await session.flush()
                prepared = await database_evidence(session)
                receipt = {
                    "backup_sha256": manifest.sha256,
                    "database": expected_db,
                    "evidence": prepared.model_dump(),
                }
                temporary = receipt_path.with_suffix(".partial")
                with temporary.open("w") as stream:
                    stream.write(json.dumps(receipt, sort_keys=True))
                    stream.flush()
                    os.fsync(stream.fileno())
                temporary.chmod(0o600)
                temporary.replace(receipt_path)
                # 先保存预期提交状态；若 commit 失败，原备份证据仍可校验重试。
                await session.commit()
                return result
            return {"tables_verified": len(evidence.counts)}
    finally:
        await engine.dispose()
