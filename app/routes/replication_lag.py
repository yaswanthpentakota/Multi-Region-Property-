from fastapi import APIRouter
from datetime import datetime, timezone
import kafka_consumer as kc

router = APIRouter()

@router.get("/replication-lag")
async def replication_lag():
    if kc.last_consumed_at is None:
        return {"lag_seconds": 0.0}
    now = datetime.now(timezone.utc)
    lag = (now - kc.last_consumed_at).total_seconds()
    return {"lag_seconds": round(lag, 3)}
