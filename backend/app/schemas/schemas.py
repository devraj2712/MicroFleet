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
    assigned_batch_id: Optional[str] = None
    assigned_rider_id: Optional[str] = None
    assigned_rider_name: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class OrderStatusUpdate(BaseModel):
    status: OrderStatus


class AssignedRouteResponse(BaseModel):
    route_id: str
    batch_id: str
    rider_id: str
    rider_name: str
    status: str
    estimated_distance_km: float
    estimated_duration_minutes: float
    ordered_stops: List[dict]
    orders: List[OrderResponse]
    created_at: datetime


# --- Geospatial and Routing Schemas ---

class LocationCoordinate(BaseModel):
    latitude: float = Field(..., ge=-90.0, le=90.0, description="Latitude in decimal degrees")
    longitude: float = Field(..., ge=-180.0, le=180.0, description="Longitude in decimal degrees")


class LocationIdentifier(LocationCoordinate):
    id: str = Field(..., min_length=1, max_length=64, description="Unique identifier for location (e.g., M-MUM-01, ORD-01)")


class SnappedPointResponse(BaseModel):
    original_latitude: float
    original_longitude: float
    snapped_node_id: int
    snapped_latitude: float
    snapped_longitude: float
    snap_distance_meters: float
    within_max_snap: bool


class RouteEstimateRequest(BaseModel):
    origin: LocationCoordinate
    destination: LocationCoordinate
    weight: str = Field(
        default="travel_time",
        pattern="^(travel_time|length)$",
        description="Routing weight metric: 'travel_time' (estimated seconds) or 'length' (network meters)",
    )


class RouteEstimateResponse(BaseModel):
    origin_snapped: SnappedPointResponse
    destination_snapped: SnappedPointResponse
    distance_meters: float
    distance_km: float
    duration_seconds: float
    duration_minutes: float
    route_node_count: int
    route_nodes: List[int]
    route_coordinates: List[List[float]] = Field(
        description="Ordered sequence of [latitude, longitude] coordinates along the road route"
    )
    metric_used: str
    attribution: str
    traffic_note: str


class RoutingMatrixRequest(BaseModel):
    locations: List[LocationIdentifier] = Field(
        ..., min_length=2, max_length=50, description="List of 2 to 50 locations for pairwise matrix computation"
    )
    weight: str = Field(
        default="travel_time",
        pattern="^(travel_time|length)$",
        description="Optimization weight metric: 'travel_time' or 'length'",
    )


class RoutingMatrixResponse(BaseModel):
    location_ids: List[str]
    distance_matrix_meters: List[List[Optional[float]]]
    duration_matrix_seconds: List[List[Optional[float]]]
    unreachable_pairs: List[List[str]] = Field(
        default_factory=list,
        description="Pairs of [source_id, target_id] where no directed road path exists",
    )
    units: dict = Field(
        default_factory=lambda: {
            "distance": "meters",
            "duration": "seconds",
        }
    )
    metadata: dict


class RoutingStatusResponse(BaseModel):
    available: bool
    network_type: Optional[str] = None
    node_count: Optional[int] = None
    edge_count: Optional[int] = None
    bounding_box_w_s_e_n: Optional[List[float]] = None
    retrieval_date: Optional[str] = None
    osmnx_version: Optional[str] = None
    networkx_version: Optional[str] = None
    travel_time_model: Optional[str] = None
    osm_attribution: str
    traffic_note: str


# --- Optimization & Preview Schemas ---

class FuzzyUrgencyPreviewRequest(BaseModel):
    order_ids: Optional[List[str]] = Field(
        None, description="Optional list of pending order IDs to score. If omitted, all pending orders up to limit are scored."
    )
    reference_time: Optional[datetime] = Field(
        None, description="Optional reference timestamp for deterministic evaluation. Defaults to current UTC time."
    )
    limit: int = Field(default=50, ge=1, le=100, description="Maximum number of orders to score in preview mode.")


class FuzzyUrgencyPreviewResponse(BaseModel):
    scored_orders: List[dict]
    summary: dict
    reference_time: datetime
    preview_mode: bool = True
    attribution: str
    traffic_note: str


class GAConfigInput(BaseModel):
    population_size: Optional[int] = Field(default=30, ge=10, le=100)
    generations: Optional[int] = Field(default=30, ge=5, le=100)
    mutation_rate: Optional[float] = Field(default=0.25, ge=0.01, le=1.0)
    crossover_rate: Optional[float] = Field(default=0.80, ge=0.1, le=1.0)
    random_seed: Optional[int] = Field(None, description="Optional random seed for reproducible evolutionary runs.")
    service_time_seconds: Optional[float] = Field(default=180.0, ge=0.0, description="Service time allowance per stop.")


class BatchOptimizationPreviewRequest(BaseModel):
    order_ids: Optional[List[str]] = Field(
        None, description="Optional subset of pending order IDs. If omitted, all eligible PENDING orders are loaded from database."
    )
    rider_ids: Optional[List[str]] = Field(
        None, description="Optional subset of available rider IDs. If omitted, all available riders in database are used."
    )
    reference_time: Optional[datetime] = Field(
        None, description="Optional reference timestamp for deterministic routing & deadline evaluations."
    )
    ga_config: Optional[GAConfigInput] = None


class ACOConfigInput(BaseModel):
    num_ants: Optional[int] = Field(default=10, ge=2, le=50, description="Number of ants per iteration")
    max_iterations: Optional[int] = Field(default=15, ge=2, le=100, description="Maximum iterations of pheromone update")
    alpha: Optional[float] = Field(default=1.0, ge=0.0, le=5.0, description="Pheromone influence factor")
    beta: Optional[float] = Field(default=2.0, ge=0.0, le=10.0, description="Heuristic desirability influence factor")
    evaporation_rate: Optional[float] = Field(default=0.15, ge=0.01, le=0.90, description="Pheromone evaporation rate")
    q_deposit: Optional[float] = Field(default=100.0, ge=1.0, le=1000.0, description="Pheromone deposit coefficient")
    random_seed: Optional[int] = Field(None, description="Random seed for reproducible route exploration")
    service_time_seconds: Optional[float] = Field(default=180.0, ge=0.0, le=1800.0, description="Service time allowance per stop")
    max_candidate_riders: Optional[int] = Field(default=5, ge=1, le=10, description="Upper bound on candidate riders evaluated per batch")


class RouteOptimizationPreviewRequest(BaseModel):
    order_ids: Optional[List[str]] = Field(
        None, description="Optional subset of pending order IDs. If omitted, all eligible PENDING orders are processed."
    )
    rider_ids: Optional[List[str]] = Field(
        None, description="Optional subset of available rider IDs. If omitted, all available riders in database are used."
    )
    reference_time: Optional[datetime] = Field(
        None, description="Optional reference timestamp for deterministic evaluation."
    )
    ga_config: Optional[GAConfigInput] = None
    aco_config: Optional[ACOConfigInput] = None


class DispatchOptimizationPreviewRequest(BaseModel):
    order_ids: Optional[List[str]] = Field(
        None, description="Optional subset of pending order IDs. If omitted, all eligible PENDING orders are processed."
    )
    rider_ids: Optional[List[str]] = Field(
        None, description="Optional subset of available rider IDs. If omitted, all available fleet riders in database are used."
    )
    reference_time: Optional[datetime] = Field(
        None, description="Optional reference timestamp for deterministic evaluation."
    )
    policy_choice: str = Field(
        default="rl",
        pattern="^(rl|nearest|least_loaded|weighted)$",
        description="Dispatch assignment policy: 'rl' (trained MaskablePPO), 'nearest', 'least_loaded', or 'weighted'",
    )
    ga_config: Optional[GAConfigInput] = None
    aco_config: Optional[ACOConfigInput] = None
    model_path: Optional[str] = Field(
        None, description="Optional custom checkpoint path for trained RL model."
    )


# --- Auth & User Profile Schemas ---

class UserResponse(BaseModel):
    id: str
    email: str
    role: str
    merchant_id: Optional[str] = None
    rider_id: Optional[str] = None
    is_active: bool = True
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class RegisterRequest(BaseModel):
    email: str
    password: Optional[str] = None
    role: str = Field(..., pattern="^(MERCHANT|RIDER)$", description="Self-registration role (MERCHANT or RIDER only).")
    display_name: Optional[str] = None
    # For merchant
    merchant_type: Optional[str] = "Retail"
    pickup_latitude: Optional[float] = Field(None, ge=-90.0, le=90.0)
    pickup_longitude: Optional[float] = Field(None, ge=-180.0, le=180.0)
    # For rider
    weight_capacity_kg: Optional[float] = Field(default=20.0, ge=1.0, le=100.0)
    package_count_capacity: Optional[int] = Field(default=10, ge=1, le=50)


class LoginRequest(BaseModel):
    email: Optional[str] = None
    password: Optional[str] = None
    id_token: Optional[str] = None


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    auth_mode: str
    user: UserResponse


class AdminProvisionRequest(BaseModel):
    email: str
    admin_secret: str
    role: str = Field(default="DISPATCHER", pattern="^(DISPATCHER|ADMIN)$")


# --- Dispatch Plan Commit Schemas ---

class DispatchCommitRequest(BaseModel):
    preview_id: str = Field(..., description="Unique draft preview identifier returned by dispatch/preview")
    approved_batch_ids: Optional[List[str]] = Field(
        None, description="Optional list of specific proposed batch IDs to commit. If omitted, all proposed feasible assignments are committed."
    )


class CommittedBatchInfo(BaseModel):
    batch_id: str
    assigned_rider_id: str
    assigned_rider_name: str
    route_id: str
    order_ids: List[str]
    total_distance_km: float
    total_duration_minutes: float
    stops_count: int


class DispatchCommitResponse(BaseModel):
    status: str = "committed"
    preview_id: str
    committed_at: datetime
    committed_batches: List[CommittedBatchInfo]
    total_orders_dispatched: int
    uncommitted_unassigned_batches: List[dict]
    message: str




