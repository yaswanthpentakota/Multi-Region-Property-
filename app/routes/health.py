from fastapi import APIRouter
from config import REGION

router = APIRouter()

@router.get("/health")
async def health():
    return {"status": "ok", "region": REGION}
