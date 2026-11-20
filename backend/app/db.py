from contextlib import contextmanager
from typing import Any, Iterator
import logging

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import settings

logger = logging.getLogger("campaignlift.db")

_pool: ConnectionPool | None = None


def init_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        logger.info("Initializing PostgreSQL connection pool")
        _pool = ConnectionPool(
            conninfo=settings.database_url,
            min_size=2,
            max_size=16,
            kwargs={"row_factory": dict_row},
            open=True,
        )
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        logger.info("Closing PostgreSQL connection pool")
        _pool.close()
        _pool = None


@contextmanager
def get_conn() -> Iterator[psycopg.Connection]:
    pool = init_pool()
    with pool.connection() as conn:
        yield conn


def fetch_all(sql: str, params: dict[str, Any] | tuple[Any, ...] | None = None) -> list[dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())


def fetch_one(sql: str, params: dict[str, Any] | tuple[Any, ...] | None = None) -> dict[str, Any] | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()
