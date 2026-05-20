import os
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.database import init_db
from app.core.redis_client import init_redis
from app.core.knowledge_base import init_knowledge_base
from app.api import screener, analytic, monitoring, scalping, health, backtest
from app.api import knowledge_base as kb_api
from app.api import enhancement as enhancement_api
from app.api import data_accumulation as data_api
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Starting BISMILLAH SUPER TRADING TERMINAL...")
    await init_db()
    await init_redis()
    await init_knowledge_base()
    logger.info("✅ All systems online — BISMILLAH!")
    yield
    logger.info("Shutting down...")

app = FastAPI(
    title="BISMILLAH SUPER TRADING TERMINAL",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(screener.router, prefix="/api/screener")
app.include_router(analytic.router, prefix="/api/analytic")
app.include_router(backtest.router, prefix="/api/backtest")
app.include_router(monitoring.router, prefix="/api/monitoring")
app.include_router(scalping.router, prefix="/ws")
app.include_router(scalping.router, prefix="/api")
app.include_router(kb_api.router)
app.include_router(enhancement_api.router)
app.include_router(data_api.router)
# Fri May 15 19:26:37 WIB 2026
# REV21 redeploy Wed May 20 07:17:10 WIB 2026
