"""CampaignLift FastAPI Application Entrypoint."""
from __future__ import annotations

from contextlib import asynccontextmanager
import logging
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import psycopg

from app.config import settings
from app.db import close_pool, init_pool
from app.routers.api import router as api_router

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("campaignlift.api")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_pool()
    logger.info("CampaignLift API ready (version=%s)", settings.app_version)
    try:
        yield
    finally:
        close_pool()


app = FastAPI(
    title="CampaignLift — Airline Marketing Promotions & Incremental Revenue Analytics API",
    version=settings.app_version,
    description="Commercial analytics, causal A/B experimentation, promotion economics, uplift modeling, and decision-support API.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3048",
        "http://127.0.0.1:3048",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    t0 = time.perf_counter()
    response = await call_next(request)
    ms = (time.perf_counter() - t0) * 1000.0
    logger.info("%s %s -> %d (%.1fms)", request.method, request.url.path, response.status_code, ms)
    return response


@app.exception_handler(psycopg.Error)
async def db_error_handler(_request: Request, exc: psycopg.Error):
    logger.exception("PostgreSQL database error")
    return JSONResponse(status_code=503, content={"error": "Database query error", "detail": str(exc)})


@app.exception_handler(Exception)
async def unhandled_error_handler(_request: Request, exc: Exception):
    logger.exception("Unhandled API exception")
    return JSONResponse(status_code=500, content={"error": "Internal server error", "detail": str(exc)})


app.include_router(api_router)
