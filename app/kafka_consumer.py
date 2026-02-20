import json
import logging
import threading
import asyncio
from datetime import datetime, timezone
from typing import Optional
from kafka import KafkaConsumer
from kafka.errors import NoBrokersAvailable
import time

from config import KAFKA_BROKER, KAFKA_TOPIC, REGION

logger = logging.getLogger(__name__)

# Shared state – last consumed message timestamp for replication-lag endpoint
last_consumed_at: Optional[datetime] = None
_loop: Optional[asyncio.AbstractEventLoop] = None
_pool = None  # will be injected at startup


def _run_consumer():
    global last_consumed_at

    # Retry connecting to Kafka (it may not be ready immediately)
    consumer = None
    for attempt in range(10):
        try:
            consumer = KafkaConsumer(
                KAFKA_TOPIC,
                bootstrap_servers=[KAFKA_BROKER],
                group_id=f"replication-consumer-{REGION}",
                value_deserializer=lambda m: json.loads(m.decode("utf-8")),
                auto_offset_reset="latest",
                enable_auto_commit=True,
            )
            logger.info("Kafka consumer connected (region=%s)", REGION)
            break
        except NoBrokersAvailable:
            logger.warning("Kafka not ready, retrying (%d/10)…", attempt + 1)
            time.sleep(6)

    if consumer is None:
        logger.error("Could not connect Kafka consumer – replication disabled")
        return

    for msg in consumer:
        data = msg.value
        msg_region = data.get("region_origin", "")

        # Only replicate updates from the OTHER region
        if msg_region == REGION:
            continue

        logger.info("Replicating property %s from region %s", data.get("id"), msg_region)

        # Apply update to local DB via asyncio
        if _loop and _pool:
            asyncio.run_coroutine_threadsafe(_apply_update(data), _loop)

        # Track for lag calculation
        try:
            last_consumed_at = datetime.fromisoformat(data["updated_at"].replace("Z", "+00:00"))
        except Exception:
            last_consumed_at = datetime.now(timezone.utc)


async def _apply_update(data: dict):
    """Apply a replicated property update to the local database."""
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE properties
                SET price      = $1,
                    version    = $2,
                    updated_at = $3
                WHERE id = $4
                """,
                float(data["price"]),
                int(data["version"]),
                datetime.fromisoformat(data["updated_at"].replace("Z", "+00:00")),
                int(data["id"]),
            )
    except Exception as e:
        logger.error("Error applying replicated update: %s", e)


def start_consumer(loop: asyncio.AbstractEventLoop, pool):
    """Start the Kafka consumer in a background daemon thread."""
    global _loop, _pool
    _loop = loop
    _pool = pool
    t = threading.Thread(target=_run_consumer, daemon=True, name="kafka-consumer")
    t.start()
    logger.info("Kafka consumer thread started")
