import uuid
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import select
from fastapi import HTTPException, status
from backend.app.models.entities import (
    Merchant,
    Rider,
    Order,
    OrderStatus,
    is_valid_status_transition,
)
from backend.app.schemas.schemas import (
    MerchantCreate,
    RiderCreate,
    OrderCreate,
)


class LogisticsService:
    @staticmethod
    def create_merchant(db: Session, merchant_in: MerchantCreate) -> Merchant:
        merchant_id = merchant_in.id or f"M-{uuid.uuid4().hex[:8].upper()}"
        existing = db.get(Merchant, merchant_id)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Merchant with ID '{merchant_id}' already exists."
            )
        
        merchant = Merchant(
            id=merchant_id,
            name=merchant_in.name,
            merchant_type=merchant_in.merchant_type,
            pickup_latitude=merchant_in.pickup_latitude,
            pickup_longitude=merchant_in.pickup_longitude,
            is_active=merchant_in.is_active,
        )
        db.add(merchant)
        db.commit()
        db.refresh(merchant)
        return merchant

    @staticmethod
    def get_merchants(db: Session, active_only: bool = False) -> List[Merchant]:
        stmt = select(Merchant)
        if active_only:
            stmt = stmt.where(Merchant.is_active == True)  # noqa: E712
        return list(db.scalars(stmt).all())

    @staticmethod
    def get_merchant(db: Session, merchant_id: str) -> Optional[Merchant]:
        return db.get(Merchant, merchant_id)

    @staticmethod
    def create_rider(db: Session, rider_in: RiderCreate) -> Rider:
        rider_id = rider_in.id or f"R-{uuid.uuid4().hex[:8].upper()}"
        existing = db.get(Rider, rider_id)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Rider with ID '{rider_id}' already exists."
            )

        rider = Rider(
            id=rider_id,
            display_name=rider_in.display_name,
            current_latitude=rider_in.current_latitude,
            current_longitude=rider_in.current_longitude,
            weight_capacity_kg=rider_in.weight_capacity_kg,
            package_count_capacity=rider_in.package_count_capacity,
            is_available=rider_in.is_available,
        )
        db.add(rider)
        db.commit()
        db.refresh(rider)
        return rider

    @staticmethod
    def get_riders(db: Session, available_only: bool = False) -> List[Rider]:
        stmt = select(Rider)
        if available_only:
            stmt = stmt.where(Rider.is_available == True)  # noqa: E712
        return list(db.scalars(stmt).all())

    @staticmethod
    def get_rider(db: Session, rider_id: str) -> Optional[Rider]:
        return db.get(Rider, rider_id)

    @staticmethod
    def update_rider_availability(db: Session, rider_id: str, is_available: bool) -> Rider:
        rider = db.get(Rider, rider_id)
        if not rider:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Rider with ID '{rider_id}' not found."
            )
        rider.is_available = is_available
        db.commit()
        db.refresh(rider)
        return rider

    @staticmethod
    def create_order(db: Session, order_in: OrderCreate) -> Order:
        # 1. Validate merchant exists
        merchant = db.get(Merchant, order_in.merchant_id)
        if not merchant:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Referenced merchant '{order_in.merchant_id}' does not exist."
            )
        if not merchant.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Referenced merchant '{order_in.merchant_id}' is inactive."
            )

        # 2. Derive pickup coordinates if not explicitly supplied
        pickup_lat = order_in.pickup_latitude if order_in.pickup_latitude is not None else merchant.pickup_latitude
        pickup_lon = order_in.pickup_longitude if order_in.pickup_longitude is not None else merchant.pickup_longitude

        # 3. Create order
        order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"
        order = Order(
            id=order_id,
            merchant_id=merchant.id,
            pickup_latitude=pickup_lat,
            pickup_longitude=pickup_lon,
            delivery_latitude=order_in.delivery_latitude,
            delivery_longitude=order_in.delivery_longitude,
            delivery_deadline=order_in.delivery_deadline,
            package_type=order_in.package_type,
            handling_requirements=order_in.handling_requirements,
            weight_kg=order_in.weight_kg,
            package_count=order_in.package_count,
            customer_priority=order_in.customer_priority,
            merchant_priority=order_in.merchant_priority,
            status=OrderStatus.PENDING.value,
        )
        db.add(order)
        db.commit()
        db.refresh(order)
        return order

    @staticmethod
    def get_orders(
        db: Session,
        status_filter: Optional[OrderStatus] = None,
        merchant_id: Optional[str] = None,
    ) -> List[Order]:
        stmt = select(Order).order_by(Order.created_at.desc())
        if status_filter:
            stmt = stmt.where(Order.status == status_filter.value)
        if merchant_id:
            stmt = stmt.where(Order.merchant_id == merchant_id)
        return list(db.scalars(stmt).all())

    @staticmethod
    def get_order(db: Session, order_id: str) -> Optional[Order]:
        return db.get(Order, order_id)

    @staticmethod
    def update_order_status(
        db: Session,
        order_id: str,
        new_status: OrderStatus,
        rider_id: Optional[str] = None,
    ) -> Order:
        order = db.get(Order, order_id)
        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Order with ID '{order_id}' not found.",
            )

        # Rider authorization check
        if rider_id:
            assigned_rider_id = None
            if order.batch_order and order.batch_order.batch and order.batch_order.batch.route:
                assigned_rider_id = order.batch_order.batch.route.rider_id

            if assigned_rider_id != rider_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Rider '{rider_id}' is not authorized to update order '{order_id}'. It is not assigned to this rider.",
                )

        current_status = OrderStatus(order.status)
        if current_status == new_status:
            return order  # Idempotent no-op

        if not is_valid_status_transition(current_status, new_status):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Illegal order status transition from '{current_status.value}' to '{new_status.value}'.",
            )

        order.status = new_status.value

        # If delivered, check if entire batch is completed
        if new_status == OrderStatus.DELIVERED and order.batch_order and order.batch_order.batch:
            batch = order.batch_order.batch
            batch_order_ids = [bo.order_id for bo in batch.batch_orders]
            other_orders = db.query(Order).filter(Order.id.in_(batch_order_ids)).all()
            if all(o.status == OrderStatus.DELIVERED.value for o in other_orders):
                batch.status = "COMPLETED"
                if batch.route:
                    batch.route.status = "COMPLETED"
                    if batch.route.rider:
                        batch.route.rider.is_available = True

        db.commit()
        db.refresh(order)
        return order

    @staticmethod
    def get_rider_assigned_routes(db: Session, rider_id: str) -> List[dict]:
        """Fetch all active assigned routes for a given rider."""
        import json
        from backend.app.models.entities import Route, RouteStatus
        from backend.app.schemas.schemas import OrderResponse

        routes = (
            db.query(Route)
            .filter(
                Route.rider_id == rider_id,
                Route.status.in_([RouteStatus.ASSIGNED.value, RouteStatus.IN_PROGRESS.value]),
            )
            .order_by(Route.created_at.desc())
            .all()
        )

        results = []
        for r in routes:
            try:
                stops = json.loads(r.ordered_stops)
            except Exception:
                stops = []

            orders_list = []
            if r.batch and r.batch.batch_orders:
                for bo in r.batch.batch_orders:
                    ord_obj = db.get(Order, bo.order_id)
                    if ord_obj:
                        resp = OrderResponse.model_validate(ord_obj)
                        resp.assigned_batch_id = r.batch_id
                        resp.assigned_rider_id = r.rider_id
                        resp.assigned_rider_name = r.rider.display_name if r.rider else "Unknown Rider"
                        orders_list.append(resp)

            results.append({
                "route_id": r.id,
                "batch_id": r.batch_id,
                "rider_id": r.rider_id,
                "rider_name": r.rider.display_name if r.rider else "Unknown Rider",
                "status": r.status,
                "estimated_distance_km": round(r.estimated_distance_m / 1000.0, 2),
                "estimated_duration_minutes": round(r.estimated_duration_s / 60.0, 1),
                "ordered_stops": stops,
                "orders": orders_list,
                "created_at": r.created_at,
            })

        return results

    @staticmethod
    def start_rider_route(db: Session, rider_id: str, route_id: str) -> dict:
        """Transition route from ASSIGNED to IN_PROGRESS."""
        from backend.app.models.entities import Route, RouteStatus

        route = db.get(Route, route_id)
        if not route:
            raise HTTPException(status_code=404, detail=f"Route '{route_id}' not found.")
        if route.rider_id != rider_id:
            raise HTTPException(status_code=403, detail="Rider is not assigned to this route.")
        if route.status != RouteStatus.ASSIGNED.value:
            raise HTTPException(status_code=400, detail=f"Route status is '{route.status}', cannot start.")

        route.status = RouteStatus.IN_PROGRESS.value
        db.commit()
        db.refresh(route)
        return {"status": "success", "route_id": route.id, "route_status": route.status}
