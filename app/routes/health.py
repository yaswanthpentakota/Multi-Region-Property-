from fastapi import APIRouter
from config import REGION

router = APIRouter()

@router.get("/health")
@router.get("/{region}/health")
async def health(region: str = None):
    return {"status": "ok", "region": REGION}
