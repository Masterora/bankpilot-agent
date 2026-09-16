"""文件职责：生成恢复核对所需的 PostgreSQL 表结构摘要。
关键边界：仅读取目录及 EXPLAIN（不使用 ANALYZE）；保留 CHECK 语义和列定义，
由 PostgreSQL 规划器统一隐式转换，不以删除表达式或字符串替换容忍结构差异。
"""

import hashlib
import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def schema_digest(session: AsyncSession) -> str:
    # 约束按有序列名标识；逻辑还原会压缩已删除列留下的物理编号空洞。
    constraints = (
        await session.execute(
            text(
                "SELECT c.relname, p.conname, p.contype::text, "
                "ARRAY(SELECT a.attname FROM unnest(p.conkey) WITH ORDINALITY k(num,ord) "
                "JOIN pg_attribute a ON a.attrelid=p.conrelid AND a.attnum=k.num "
                "ORDER BY k.ord), "
                "ARRAY(SELECT a.attname FROM unnest(p.confkey) WITH ORDINALITY k(num,ord) "
                "JOIN pg_attribute a ON a.attrelid=p.confrelid AND a.attnum=k.num "
                "ORDER BY k.ord), "
                "p.confrelid::regclass::text, p.confupdtype::text, p.confdeltype::text, "
                "p.confmatchtype::text, "
                "p.condeferrable, p.condeferred, p.convalidated, "
                "pg_get_expr(p.conbin,p.conrelid,false) AS expression "
                "FROM pg_constraint p JOIN pg_class c ON p.conrelid=c.oid "
                "JOIN pg_namespace n ON c.relnamespace=n.oid "
                "WHERE n.nspname='public' ORDER BY c.relname,p.conname"
            )
        )
    ).all()
    connection = await session.connection()
    quote = connection.dialect.identifier_preparer.quote_identifier
    definitions = []
    for row in constraints:
        if not row.convalidated:
            raise ValueError("Database has unvalidated constraints")
        definition = list(row)
        if row.expression is not None:
            # 仅比较输出表达式，不比较随数据/统计变化的扫描方式、成本和估算行数。
            # 表名由目录读取并引用，表达式来自 PostgreSQL 自身，不接收客户端 SQL。
            plan = await connection.exec_driver_sql(
                f"EXPLAIN (VERBOSE, FORMAT JSON) SELECT {row.expression} "
                f"FROM ONLY public.{quote(row.relname)} AS evidence_row"
            )
            output = plan.scalar_one()[0]["Plan"].get("Output")
            if not isinstance(output, list) or len(output) != 1:
                raise ValueError("Cannot normalize constraint expression")
            definition[-1] = output[0]
        definitions.append(definition)
    columns = (
        await session.execute(
            text(
                "SELECT c.relname, a.attname, format_type(a.atttypid,a.atttypmod), "
                "a.attnotnull, a.attidentity::text, a.attgenerated::text, "
                "cn.nspname, co.collname, pg_get_expr(d.adbin,d.adrelid,false) "
                "FROM pg_attribute a JOIN pg_class c ON a.attrelid=c.oid "
                "JOIN pg_namespace n ON c.relnamespace=n.oid "
                "LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum "
                "LEFT JOIN pg_collation co ON co.oid=a.attcollation "
                "LEFT JOIN pg_namespace cn ON cn.oid=co.collnamespace "
                "WHERE n.nspname='public' AND c.relkind IN ('r','p') "
                "AND a.attnum>0 AND NOT a.attisdropped ORDER BY c.relname,a.attnum"
            )
        )
    ).all()
    indexes = (
        await session.execute(
            text(
                "SELECT tablename,indexname,indexdef FROM pg_indexes "
                "WHERE schemaname='public' ORDER BY tablename,indexname"
            )
        )
    ).all()
    # 规划器规范形式限定同一 PostgreSQL 主版本；跨主版本迁移必须独立验收。
    major = int(str(await session.scalar(text("SHOW server_version_num")))) // 10000
    evidence = {
        "postgres_major": major,
        "constraints": definitions,
        "columns": [list(row) for row in columns],
        "indexes": [list(row) for row in indexes],
    }
    return hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()
