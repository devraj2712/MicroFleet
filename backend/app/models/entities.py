import enum
from datetime import datetime, timezone
from typing import Optional, Set
from sqlalchemy import (
    Column,
    String,
    Float,
    Integer,
    Boolean,
    DateTime,
    ForeignKey,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import relationship
from backend.app.core.database import Base


class OrderStatus(str, enum.Enum):
    PENDING = "PENDING"
    BATCHED = "BATCHED"
    DISPATCHED = "DISPATCHED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class BatchStatus(str, enum.Enum):
    OPEN = "OPEN"
    OPTIMIZING = "OPTIMIZING"
    ASSIGNED = "ASSIGNED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RouteStatus(str, enum.Enum):
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# Permitted Order Status Transitions
PERMITTED_ORDER_TRANSITIONS: dict[OrderStatus, Set[OrderStatus]] = {
    OrderStatus.PENDING: {OrderStatus.BATCHED, OrderStatus.CANCELLED},
    OrderStatus.BATCHED: {OrderStatus.DISPATCHED, OrderStatus.PENDING, OrderStatus.CANCELLED},
    OrderStatus.DISPATCHED: {OrderStatus.DELIVERED, OrderStatus.CANCELLED},
    OrderStatus.DELIVERED: set(),  # Terminal
    OrderStatus.CANCELLED: set(),  # Terminal
}


def is_valid_status_transition(current: OrderStatus, target: OrderStatus) -> bool:
    """Validate whether an order status transition is permitted."""
    allowed = PERMITTED_ORDER_TRANSITIONS.get(current, set())
    return target in allowed


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Merchant(Base):
    __tablename__ = "merchants"

    id = Column(String(64), primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    merchant_type = Column(String(64), nullable=False, default="Retail")
    pickup_latitude = Column(Float, nullable=False)
    pickup_longitude = Column(Float, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    # Relationships
    orders = relationship("Order", back_populates="merchant", cascade="all, delete-orphan")


class Rider(Base):
    __tablename__ = "riders"

    id = Column(String(64), primary_key=True, index=True)
    display_name = Column(String(255), nullable=False)
    current_latitude = Column(Float, nullable=False)
    current_longitude = Column(Float, nullable=False)
    weight_capacity_kg = Column(Float, nullable=False, default=20.0)
    package_count_capacity = Column(Integer, nullable=False, default=10)
    is_available = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    # Relationships
    routes = relationship("Route", back_populates="rider")


class Order(Base):
    __tablename__ = "orders"

    id = Column(String(64), primary_key=True, index=True)
    merchant_id = Column(String(64), ForeignKey("merchants.id", ondelete="RESTRICT"), nullable=False, index=True)
    pickup_latitude = Column(Float, nullable=False)
    pickup_longitude = Column(Float, nullable=False)
    delivery_latitude = Column(Float, nullable=False)
    delivery_longitude = Column(Float, nullable=False)
    delivery_deadline = Column(DateTime(timezone=True), nullable=False)
    package_type = Column(String(64), nullable=False, default="PARCEL")
    handling_requirements = Column(String(255), nullable=True)
    weight_kg = Column(Float, nullable=False, default=1.0)
    package_count = Column(Integer, nullable=False, default=1)
    customer_priority = Column(String(32), nullable=False, default="STANDARD")
    merchant_priority = Column(Integer, nullable=False, default=1)
    status = Column(String(32), nullable=False, default=OrderStatus.PENDING.value, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    # Relationships
    merchant = relationship("Merchant", back_populates="orders")
    batch_order = relationship("BatchOrder", back_populates="order", uselist=False, cascade="all, delete-orphan")


class Batch(Base):
    __tablename__ = "batches"

    id = Column(String(64), primary_key=True, index=True)
    status = Column(String(32), nullable=False, default=BatchStatus.OPEN.value, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    objective_score = Column(Float, nullable=True)

    # Relationships
    batch_orders = relationship("BatchOrder", back_populates="batch", cascade="all, delete-orphan")
    route = relationship("Route", back_populates="batch", uselist=False, cascade="all, delete-orphan")


class BatchOrder(Base):
    __tablename__ = "batch_orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    batch_id = Column(String(64), ForeignKey("batches.id", ondelete="CASCADE"), nullable=False, index=True)
    order_id = Column(String(64), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)

    # Relationships
    batch = relationship("Batch", back_populates="batch_orders")
    order = relationship("Order", back_populates="batch_order")

    __table_args__ = (
        UniqueConstraint("order_id", name="uq_batch_order_order_id"),
        Index("idx_batch_order_lookup", "batch_id", "order_id"),
    )


class Route(Base):
    __tablename__ = "routes"

    id = Column(String(64), primary_key=True, index=True)
    batch_id = Column(String(64), ForeignKey("batches.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    rider_id = Column(String(64), ForeignKey("riders.id", ondelete="SET NULL"), nullable=True, index=True)
    ordered_stops = Column(Text, nullable=False, default="[]")  # JSON encoded list of stops
    estimated_distance_m = Column(Float, nullable=False, default=0.0)
    estimated_duration_s = Column(Float, nullable=False, default=0.0)
    status = Column(String(32), nullable=False, default=RouteStatus.ASSIGNED.value, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    # Relationships
    batch = relationship("Batch", back_populates="route")
    rider = relationship("Rider", back_populates="routes")
