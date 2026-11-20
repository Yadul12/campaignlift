"""SQL Analytics Library Service: Parses curated analytical SQL queries, executes safely read-only, and returns EXPLAIN plans."""
from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

from app.config import settings
from app.db import get_conn


def _parse_sql_library() -> list[dict[str, Any]]:
    path = Path(settings.sql_analytics_dir) / "queries.sql"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    blocks = text.split("-- @id:")
    queries: list[dict[str, Any]] = []

    for block in blocks[1:]:
        lines = block.splitlines()
        qid = lines[0].strip()
        meta: dict[str, str] = {"id": qid}
        sql_lines: list[str] = []
        in_sql = False
        for line in lines[1:]:
            stripped = line.strip()
            if not in_sql and stripped.startswith("-- @"):
                parts = stripped[4:].split(":", 1)
                if len(parts) == 2:
                    meta[parts[0].strip()] = parts[1].strip()
            else:
                if stripped or in_sql:
                    in_sql = True
                    sql_lines.append(line)
        sql_text = "\n".join(sql_lines).strip()
        if sql_text.endswith(";"):
            sql_text = sql_text[:-1].strip()
        queries.append({
            "id": meta.get("id", qid),
            "title": meta.get("title", qid),
            "category": meta.get("category", "Analytics"),
            "techniques": [t.strip() for t in meta.get("techniques", "").split(",") if t.strip()],
            "indexes": [i.strip() for i in meta.get("indexes", "").split(",") if i.strip()],
            "business_decision": meta.get("decision", ""),
            "sql": sql_text,
        })
    return queries


def list_sql_queries() -> list[dict[str, Any]]:
    return _parse_sql_library()


def execute_curated_query(query_id: str, include_explain: bool = True) -> dict[str, Any] | None:
    queries = {q["id"]: q for q in _parse_sql_library()}
    q = queries.get(query_id)
    if not q:
        return None

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Read-only execution guard
            cur.execute("SET LOCAL TRANSACTION READ ONLY;")
            explain_lines: list[str] = []
            if include_explain:
                cur.execute(f"EXPLAIN (ANALYZE, BUFFERS false, FORMAT TEXT) {q['sql']}")
                explain_lines = [list(r.values())[0] for r in cur.fetchall()]

            cur.execute(q["sql"])
            raw_rows = cur.fetchall()
            columns = [desc.name for desc in cur.description] if cur.description else []

            clean_rows = []
            for r in raw_rows:
                clean_rows.append({
                    k: (float(v) if hasattr(v, "as_tuple") else (str(v) if hasattr(v, "isoformat") else v))
                    for k, v in r.items()
                })
        conn.rollback()

    return {
        "query": q,
        "columns": columns,
        "row_count": len(clean_rows),
        "rows": clean_rows,
        "explain_plan": explain_lines,
    }


def export_sql_query_csv(query_id: str) -> bytes | None:
    res = execute_curated_query(query_id, include_explain=False)
    if not res:
        return None
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=res["columns"])
    writer.writeheader()
    for row in res["rows"]:
        writer.writerow(row)
    return buf.getvalue().encode("utf-8")


def get_data_audit_summary() -> dict[str, Any]:
    tables = [
        "customers", "customer_segments", "campaigns", "campaign_channels",
        "campaign_assignments", "campaign_exposures", "bookings", "booking_items",
        "ticket_revenue", "discount_transactions", "loyalty_rewards", "route_markets",
        "marketing_costs", "customer_responses", "calendar_dimension",
        "experiment_results_store", "ml_model_runs", "customer_propensity_scores",
    ]
    counts = []
    with get_conn() as conn:
        with conn.cursor() as cur:
            for tbl in tables:
                cur.execute(f"SELECT COUNT(*) AS cnt FROM {tbl}")
                counts.append({"table_name": tbl, "row_count": int(cur.fetchone()["cnt"])})
            cur.execute("SELECT meta_key, meta_value FROM dataset_metadata ORDER BY meta_key")
            meta = {r["meta_key"]: r["meta_value"] for r in cur.fetchall()}
            cur.execute(
                """
                SELECT
                    experiment_type,
                    COUNT(*) AS campaigns,
                    COUNT(*) FILTER (WHERE srm_passed = TRUE) AS srm_passed,
                    ROUND(AVG(max_covariate_smd)::NUMERIC, 4)::FLOAT8 AS avg_max_smd,
                    COUNT(*) FILTER (WHERE is_statistically_significant = TRUE) AS sig_campaigns
                FROM experiment_results_store
                GROUP BY experiment_type
                ORDER BY experiment_type DESC
                """
            )
            exp_audit = cur.fetchall()
            cur.execute("SELECT version, applied_at::TEXT AS applied_at FROM schema_migrations ORDER BY version")
            migrations = cur.fetchall()

    return {
        "dataset_label": settings.dataset_label,
        "metadata": meta,
        "table_counts": counts,
        "experiment_audit": exp_audit,
        "migrations": migrations,
    }
