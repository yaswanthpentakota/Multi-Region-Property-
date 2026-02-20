from pydantic import BaseModel
from typing import Optional
from decimal import Decimal
from datetime import datetime

class PropertyUpdateRequest(BaseModel):
    price: float
    version: int

class PropertyResponse(BaseModel):
    id: int
    price: float
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None
    region_origin: str
    version: int
    updated_at: datetime

class ReplicationLagResponse(BaseModel):
    lag_seconds: float
