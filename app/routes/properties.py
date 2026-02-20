import json
import logging
from fastapi import APIRouter, Request, HTTPException, Header
from typing import Optional

from database import get_pool
from models import PropertyUpdateRequest, PropertyResponse
from kafka_producer import publish_update
from config import REGION

logger = logging.getLogger(__name__)
router = APIRouter()


@router.put("/{region}/properties/{property_id}")
async def update_property(
    region: str,
    property_id: int,
    body: PropertyUpdateRequest,
    x_request_id: Optional[str] = Header(default=None),
):
    pool = await get_pool()

    async with pool.acquire() as conn:

        # ── 1. Idempotency check ─────────────────────────────────────────
        if x_request_id:
            existing = await conn.fetchrow(
                "SELECT response_body FROM idempotency_store WHERE request_id = $1",
                x_request_id,
            )
            if existing:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": "duplicate_request",
                        "message": f"Request ID '{x_request_id}' has already been processed.",
                    },
                )

        # ── 2. Load current property ─────────────────────────────────────
        row = await conn.fetchrow(
            "SELECT id, price, bedrooms, bathrooms, region_origin, version, updated_at "
            "FROM properties WHERE id = $1",
            property_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail=f"Property {property_id} not found")

        current_version = row["version"]

        # ── 3. Optimistic locking ────────────────────────────────────────
        if body.version != current_version:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "version_conflict",
                    "message": (
                        f"Version conflict: expected {current_version}, got {body.version}. "
                        "Re-fetch the property and retry with the latest version."
                    ),
                    "current_version": current_version,
                    "provided_version": body.version,
                },
            )

        # ── 4. Atomic update (WHERE version = $3 guards race conditions) ─
        updated = await conn.fetchrow(
            """
            UPDATE properties
            SET price      = $1,
                version    = version + 1,
                updated_at = NOW()
            WHERE id = $2 AND version = $3
            RETURNING id, price, bedrooms, bathrooms, region_origin, version, updated_at
            """,
            body.price,
            property_id,
            body.version,
        )

        if not updated:
            # Another concurrent request already changed the version
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "version_conflict",
                    "message": "Concurrent update detected. Re-fetch the property and retry.",
                },
            )

        # ── 5. Build response dict ───────────────────────────────────────
        result = {
            "id": updated["id"],
            "price": float(updated["price"]),
            "bedrooms": updated["bedrooms"],
            "bathrooms": updated["bathrooms"],
            "region_origin": updated["region_origin"],
            "version": updated["version"],
            "updated_at": updated["updated_at"].isoformat(),
        }

        # ── 6. Store idempotency record ──────────────────────────────────
        if x_request_id:
            await conn.execute(
                "INSERT INTO idempotency_store (request_id, response_body) VALUES ($1, $2) "
                "ON CONFLICT (request_id) DO NOTHING",
                x_request_id,
                json.dumps(result),
            )

    # ── 7. Publish to Kafka (outside DB transaction) ─────────────────
    try:
        publish_update(result)
    except Exception as e:
        logger.error("Kafka publish failed (update already committed): %s", e)

    return result
