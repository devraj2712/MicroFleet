from datetime import datetime, timezone
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator, ConfigDict
from backend.app.models.entities import OrderStatus, BatchStatus, RouteStatus


class HealthResponse(BaseModel):
    status: str
    app: str
    version: str
    database: str
    timestamp: datetime


# --- Merchant Schemas ---

class MerchantBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    merchant_type: str = Field(default="Retail", max_length=64)
    pickup_latitude: float = Field(..., ge=-90.0, le=90.0)
    pickup_longitude: float = Field(..., ge=-180.0, le=180.0)
    is_active: bool = True


class MerchantCreate(MerchantBase):
    id: Optional[str] = Field(None, max_length=64, description="Optional custom ID (e.g., M-101)")


class MerchantResponse(MerchantBase):
    id: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


# --- Rider Schemas ---

class RiderBase(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=255)
    current_latitude: float = Field(..., ge=-90.0, le=90.0)
    current_longitude: float = Field(..., ge=-180.0, le=180.0)
    weight_capacity_kg: float = Field(..., gt=0.0)
    package_count_capacity: int = Field(..., gt=0)
    is_available: bool = True


class RiderCreate(RiderBase):
    id: Optional[str] = Field(None, max_length=64, description="Optional custom ID (e.g., R-201)")


class RiderResponse(RiderBase):
    id: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class RiderAvailabilityUpdate(BaseModel):
    is_available: bool


# --- Order Schemas ---

class OrderCreate(BaseModel):
    merchant_id: str = Field(..., min_length=1)
    pickup_latitude: Optional[float] = Field(None, ge=-90.0, le=90.0)
    pickup_longitude: Optional[float] = Field(None, ge=-180.0, le=180.0)
    delivery_latitude: float = Field(..., ge=-90.0, le=90.0)
    delivery_longitude: float = Field(..., ge=-180.0, le=180.0)
    delivery_deadline: datetime
    package_type: str = Field(default="PARCEL", min_length=1, max_length=64)
    handling_requirements: Optional[str] = Field(None, max_length=255)
    weight_kg: float = Field(..., gt=0.0)
    package_count: int = Field(default=1, ge=1)
    customer_priority: str = Field(default="STANDARD", max_length=32)
    merchant_priority: int = Field(default=1, ge=1, le=10)

    @field_validator("delivery_deadline")
    @classmethod
    def validate_deadline_timezone(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            # If naive datetime, assume UTC
            return v.replace(tzinfo=timezone.utc)
        return v


class OrderResponse(BaseModel):
    id: str
    merchant_id: str
    pickup_latitude: float
    pickup_longitude: float
    delivery_latitude: float
    delivery_longitude: float
    delivery_deadline: datetime
    package_type: str
    handling_requirements: Optional[str]
    weight_kg: float
    package_count: int
    customer_priority: str
    merchant_priority: int
    status: OrderStatus
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class OrderStatusUpdate(BaseModel):
    status: OrderStatus
