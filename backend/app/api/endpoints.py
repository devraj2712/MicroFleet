from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from backend.app.core.database import get_db
from backend.app.models.entities import OrderStatus
from backend.app.schemas.schemas import (
    MerchantCreate,
    MerchantResponse,
    RiderCreate,
    RiderResponse,
    RiderAvailabilityUpdate,
    OrderCreate,
    OrderResponse,
    OrderStatusUpdate,
)
from backend.app.services.logistics_service import LogisticsService

api_router = APIRouter()


# --- Merchant Endpoints ---

@api_router.post(
    "/merchants",
    response_model=MerchantResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Merchant",
    description="Register a new local merchant with designated pickup coordinates. [DEV ONLY - No Auth]",
)
def create_merchant(merchant_in: MerchantCreate, db: Session = Depends(get_db)):
    return LogisticsService.create_merchant(db, merchant_in)


@api_router.get(
    "/merchants",
    response_model=List[MerchantResponse],
    summary="List Merchants",
    description="Retrieve all registered merchants. Optionally filter by active status.",
)
def list_merchants(active_only: bool = Query(False), db: Session = Depends(get_db)):
    return LogisticsService.get_merchants(db, active_only=active_only)


# --- Rider Endpoints ---

@api_router.post(
    "/riders",
    response_model=RiderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register Fleet Rider",
    description="Register a delivery rider with initial location and vehicle capacity. [DEV ONLY - No Auth]",
)
def create_rider(rider_in: RiderCreate, db: Session = Depends(get_db)):
    return LogisticsService.create_rider(db, rider_in)


@api_router.get(
    "/riders",
    response_model=List[RiderResponse],
    summary="List Fleet Riders",
    description="Retrieve fleet riders with current positions and status.",
)
def list_riders(available_only: bool = Query(False), db: Session = Depends(get_db)):
    return LogisticsService.get_riders(db, available_only=available_only)


@api_router.patch(
    "/riders/{rider_id}/availability",
    response_model=RiderResponse,
    summary="Update Rider Availability",
    description="Toggle whether a rider is on-duty and available for dispatch.",
)
def update_rider_availability(
    rider_id: str,
    update_in: RiderAvailabilityUpdate,
    db: Session = Depends(get_db),
):
    return LogisticsService.update_rider_availability(db, rider_id, update_in.is_available)


# --- Order Endpoints ---

@api_router.post(
    "/orders",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Order",
    description="Create and persist a delivery order linked to an active merchant. [DEV ONLY - No Auth]",
)
def create_order(order_in: OrderCreate, db: Session = Depends(get_db)):
    return LogisticsService.create_order(db, order_in)


@api_router.get(
    "/orders",
    response_model=List[OrderResponse],
    summary="List Orders",
    description="Retrieve all orders, optionally filtered by status.",
)
def list_orders(
    status_filter: Optional[OrderStatus] = Query(None, alias="status"),
    db: Session = Depends(get_db),
):
    return LogisticsService.get_orders(db, status_filter=status_filter)


@api_router.get(
    "/orders/{order_id}",
    response_model=OrderResponse,
    summary="Get Order Details",
    description="Retrieve details of a single order by its ID.",
)
def get_order(order_id: str, db: Session = Depends(get_db)):
    order = LogisticsService.get_order(db, order_id)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order with ID '{order_id}' not found.",
        )
    return order


@api_router.patch(
    "/orders/{order_id}/status",
    response_model=OrderResponse,
    summary="Update Order Status",
    description="Transition an order to a new lifecycle status following strict state machine rules.",
)
def update_order_status(
    order_id: str,
    status_update: OrderStatusUpdate,
    db: Session = Depends(get_db),
):
    return LogisticsService.update_order_status(db, order_id, status_update.status)
