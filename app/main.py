import asyncio
import logging
import contextlib
from fastapi import FastAPI

from config import REGION
from database import get_pool, close_pool
import kafka_consumer
from routes.health import router as health_router
from routes.properties import router as properties_router
from routes.replication_lag import router as lag_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────
    logger.info("Starting backend – region=%s", REGION)
    pool = await get_pool()
    loop = asyncio.get_event_loop()
    kafka_consumer.start_consumer(loop, pool)
    yield
    # ── Shutdown ─────────────────────────────────────────────────────
    await close_pool()


app = FastAPI(title=f"Property Listing API ({REGION.upper()})", lifespan=lifespan)

# Mount routes WITHOUT a prefix – NGINX strips the region prefix from the path
app.include_router(health_router)
app.include_router(properties_router)
app.include_router(lag_router)
