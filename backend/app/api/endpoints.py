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
from backend.app.api.routing import router as routing_router
from backend.app.api.optimization import router as optimization_router
from backend.app.api.auth import router as auth_router
from backend.app.core.auth import get_optional_current_user
from backend.app.models.entities import Order, User, UserRole

api_router = APIRouter()

# Mount authentication endpoints
api_router.include_router(auth_router)

# Mount routing & geospatial endpoints
api_router.include_router(routing_router)

# Mount intelligent optimization endpoints
api_router.include_router(optimization_router)



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


def _format_order(order: Order, db: Session) -> OrderResponse:
    batch_id = None
    rider_id = None
    rider_name = None
    if order.batch_order and order.batch_order.batch:
        batch_id = order.batch_order.batch_id
        route = order.batch_order.batch.route
        if route:
            rider_id = route.rider_id
            if route.rider:
                rider_name = route.rider.display_name

    resp = OrderResponse.model_validate(order)
    resp.assigned_batch_id = batch_id
    resp.assigned_rider_id = rider_id
    resp.assigned_rider_name = rider_name
    return resp


# --- Order Endpoints ---

@api_router.post(
    "/orders",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Order",
    description="Create and persist a delivery order linked to an active merchant.",
)
def create_order(
    order_in: OrderCreate,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_current_user),
):
    if current_user and current_user.role == UserRole.MERCHANT.value:
        if current_user.merchant_id:
            if order_in.merchant_id and order_in.merchant_id != current_user.merchant_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Access denied: You are authorized as merchant '{current_user.merchant_id}', and cannot create orders for '{order_in.merchant_id}'.",
                )
            order_in.merchant_id = current_user.merchant_id

    order = LogisticsService.create_order(db, order_in)
    return _format_order(order, db)


@api_router.get(
    "/orders",
    response_model=List[OrderResponse],
    summary="List Orders",
    description="Retrieve all orders, optionally filtered by status or merchant profile.",
)
def list_orders(
    status_filter: Optional[OrderStatus] = Query(None, alias="status"),
    merchant_id: Optional[str] = Query(None, alias="merchant_id"),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_current_user),
):
    # Enforce merchant data isolation
    if current_user and current_user.role == UserRole.MERCHANT.value:
        if current_user.merchant_id:
            merchant_id = current_user.merchant_id

    orders = LogisticsService.get_orders(db, status_filter=status_filter, merchant_id=merchant_id)
    return [_format_order(o, db) for o in orders]


@api_router.get(
    "/orders/{order_id}",
    response_model=OrderResponse,
    summary="Get Order Details",
    description="Retrieve details of a single order by its ID.",
)
def get_order(
    order_id: str,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_current_user),
):
    order = LogisticsService.get_order(db, order_id)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order with ID '{order_id}' not found.",
        )
    if current_user and current_user.role == UserRole.MERCHANT.value:
        if current_user.merchant_id and order.merchant_id != current_user.merchant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: You are not authorized to view orders belonging to other merchants.",
            )
    return _format_order(order, db)


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
    current_user: Optional[User] = Depends(get_optional_current_user),
):
    rider_filter_id = None
    if current_user and current_user.role == UserRole.RIDER.value:
        rider_filter_id = current_user.rider_id

    order = LogisticsService.update_order_status(
        db, order_id, status_update.status, rider_id=rider_filter_id
    )
    return _format_order(order, db)


# --- Rider Assigned Routes & Delivery Progression ---

@api_router.get(
    "/riders/{rider_id}/assigned-routes",
    summary="List Rider Assigned Routes",
    description="Retrieve active and assigned delivery routes with stop sequences and order details for a rider.",
)
def get_rider_assigned_routes(
    rider_id: str,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_current_user),
):
    if current_user:
        if current_user.role == UserRole.MERCHANT.value:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: Merchants are not authorized to view rider routes.",
            )
        if current_user.role == UserRole.RIDER.value:
            if current_user.rider_id and current_user.rider_id != rider_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Access denied: You are authenticated as rider '{current_user.rider_id}', and cannot view routes for rider '{rider_id}'.",
                )
    return LogisticsService.get_rider_assigned_routes(db, rider_id)


@api_router.post(
    "/riders/{rider_id}/routes/{route_id}/start",
    summary="Start Route",
    description="Transition an assigned route to IN_PROGRESS when the rider commences deliveries.",
)
def start_rider_route(
    rider_id: str,
    route_id: str,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_current_user),
):
    if current_user:
        if current_user.role == UserRole.MERCHANT.value:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: Merchants cannot start rider routes.",
            )
        if current_user.role == UserRole.RIDER.value:
            if current_user.rider_id and current_user.rider_id != rider_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied: You cannot start routes assigned to other riders.",
                )
    return LogisticsService.start_rider_route(db, rider_id, route_id)
