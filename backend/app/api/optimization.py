import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.core.auth import require_dispatcher
from backend.app.core.config import settings
from backend.app.core.database import get_db
from backend.app.intelligence.aco import (
    ACOConfig,
    ACORoutingEngine,
    RoutesPreviewResult,
)
from backend.app.intelligence.fuzzy.fuzzy_urgency import FuzzyUrgencyEngine
from backend.app.intelligence.ga.ga_batching import (
    BaselineComparisonResult,
    GABatchingEngine,
    GAConfig,
)
from backend.app.intelligence.osm.osm_service import (
    DEFAULT_ATTRIBUTION,
    DEFAULT_TRAFFIC_NOTE,
    NetworkUnavailableError,
)
from backend.app.intelligence.rl import (
    DispatchPreviewResult,
    RLDispatchService,
)
from backend.app.models.entities import (
    Batch,
    BatchOrder,
    BatchStatus,
    DispatchDraft,
    Order,
    OrderStatus,
    Rider,
    Route,
    RouteStatus,
    User,
)
from backend.app.schemas.schemas import (
    BatchOptimizationPreviewRequest,
    CommittedBatchInfo,
    DispatchCommitRequest,
    DispatchCommitResponse,
    DispatchOptimizationPreviewRequest,
    FuzzyUrgencyPreviewRequest,
    FuzzyUrgencyPreviewResponse,
    RouteOptimizationPreviewRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/optimization", tags=["Optimization & Intelligent Systems"])


@router.post(
    "/urgency/preview",
    response_model=FuzzyUrgencyPreviewResponse,
    status_code=status.HTTP_200_OK,
    summary="Preview Fuzzy Urgency Scoring",
    description="Calculates interpretable fuzzy urgency scores, deadline slack, and contributing rules for pending delivery orders without modifying database state.",
)
def preview_urgency(
    request: FuzzyUrgencyPreviewRequest,
    db: Session = Depends(get_db),
):
    now = request.reference_time or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    # 1. Fetch target orders
    if request.order_ids:
        orders = db.query(Order).filter(Order.id.in_(request.order_ids)).all()
        found_ids = {o.id for o in orders}
        missing_ids = set(request.order_ids) - found_ids
        if missing_ids:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Orders not found: {sorted(list(missing_ids))}",
            )
        # Check non-pending orders
        non_pending = [o.id for o in orders if o.status != OrderStatus.PENDING.value]
        if non_pending:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Orders must have PENDING status for urgency scoring. Non-pending: {non_pending}",
            )
    else:
        orders = (
            db.query(Order)
            .filter(Order.status == OrderStatus.PENDING.value)
            .order_by(Order.created_at.asc())
            .limit(request.limit)
            .all()
        )

    if not orders:
        return FuzzyUrgencyPreviewResponse(
            scored_orders=[],
            summary={
                "total_orders": 0,
                "low_count": 0,
                "medium_count": 0,
                "high_count": 0,
                "critical_count": 0,
                "average_urgency": 0.0,
            },
            reference_time=now,
            preview_mode=True,
            attribution=DEFAULT_ATTRIBUTION,
            traffic_note=DEFAULT_TRAFFIC_NOTE,
        )

    # 2. Score orders via FuzzyUrgencyEngine
    scored_results = []
    category_counts = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}
    total_score = 0.0

    for o in orders:
        res = FuzzyUrgencyEngine.score_order(o, reference_time=now)
        cat_str = res.urgency_category.value
        category_counts[cat_str] = category_counts.get(cat_str, 0) + 1
        total_score += res.urgency_score
        scored_results.append(res.model_dump())

    avg_score = round(total_score / len(orders), 2) if orders else 0.0

    return FuzzyUrgencyPreviewResponse(
        scored_orders=scored_results,
        summary={
            "total_orders": len(orders),
            "low_count": category_counts.get("LOW", 0),
            "medium_count": category_counts.get("MEDIUM", 0),
            "high_count": category_counts.get("HIGH", 0),
            "critical_count": category_counts.get("CRITICAL", 0),
            "average_urgency": avg_score,
        },
        reference_time=now,
        preview_mode=True,
        attribution=DEFAULT_ATTRIBUTION,
        traffic_note=DEFAULT_TRAFFIC_NOTE,
    )


@router.post(
    "/batches/preview",
    response_model=BaselineComparisonResult,
    status_code=status.HTTP_200_OK,
    summary="Preview GA Delivery Batches & Baseline Comparison",
    description="Optimizes shared delivery batch allocation using a Genetic Algorithm with vehicle capacity, package compatibility, and route precedence constraints. Compares against independent solo deliveries and greedy urgency batching. Does NOT alter database records.",
)
def preview_batches(
    request: BatchOptimizationPreviewRequest,
    db: Session = Depends(get_db),
):
    now = request.reference_time or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    # 1. Fetch and validate candidate orders
    if request.order_ids:
        orders = db.query(Order).filter(Order.id.in_(request.order_ids)).all()
        found_ids = {o.id for o in orders}
        missing_ids = set(request.order_ids) - found_ids
        if missing_ids:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Orders not found: {sorted(list(missing_ids))}",
            )
        non_pending = [o.id for o in orders if o.status != OrderStatus.PENDING.value]
        if non_pending:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Only PENDING orders can be grouped into batches. Non-pending: {non_pending}",
            )
    else:
        orders = db.query(Order).filter(Order.status == OrderStatus.PENDING.value).all()

    # 2. Fetch and validate available fleet riders
    if request.rider_ids:
        riders = db.query(Rider).filter(Rider.id.in_(request.rider_ids)).all()
        found_rider_ids = {r.id for r in riders}
        missing_riders = set(request.rider_ids) - found_rider_ids
        if missing_riders:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Riders not found: {sorted(list(missing_riders))}",
            )
    else:
        riders = db.query(Rider).filter(Rider.is_available.is_(True)).all()

    if not riders:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No available fleet riders available to serve delivery batches.",
        )

    # 3. Configure GA hyperparameters
    ga_cfg = GAConfig()
    if request.ga_config:
        if request.ga_config.population_size is not None:
            ga_cfg.population_size = request.ga_config.population_size
        if request.ga_config.generations is not None:
            ga_cfg.generations = request.ga_config.generations
        if request.ga_config.mutation_rate is not None:
            ga_cfg.mutation_rate = request.ga_config.mutation_rate
        if request.ga_config.crossover_rate is not None:
            ga_cfg.crossover_rate = request.ga_config.crossover_rate
        if request.ga_config.random_seed is not None:
            ga_cfg.random_seed = request.ga_config.random_seed
        if request.ga_config.service_time_seconds is not None:
            ga_cfg.service_time_seconds = request.ga_config.service_time_seconds

    # 4. Execute GA batching optimization and baseline comparisons
    try:
        return GABatchingEngine.optimize_batches(
            orders=orders,
            riders=riders,
            reference_time=now,
            config=ga_cfg,
        )
    except NetworkUnavailableError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Road network unavailable for batch optimization: {str(e)}",
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )
    except Exception as e:
        logger.exception("Unexpected error during batch optimization preview: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Batch optimization failed: {str(e)}",
        )


@router.post(
    "/routes/preview",
    response_model=RoutesPreviewResult,
    status_code=status.HTTP_200_OK,
    summary="Preview ACO Pickup-and-Delivery Route Optimization & Greedy Baseline",
    description="Optimizes stop-level pickup-and-delivery routes for GA-generated batches using Ant Colony Optimization (ACO). Enforces pickup-before-delivery precedence, onboard capacity throughout the route, and delivery deadlines. Evaluates candidate routes for eligible fleet riders and compares against a deterministic greedy baseline.",
)
def preview_routes(
    request: RouteOptimizationPreviewRequest,
    db: Session = Depends(get_db),
):
    now = request.reference_time or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    # 1. Fetch and validate candidate orders
    if request.order_ids:
        orders = db.query(Order).filter(Order.id.in_(request.order_ids)).all()
        found_ids = {o.id for o in orders}
        missing_ids = set(request.order_ids) - found_ids
        if missing_ids:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Orders not found: {sorted(list(missing_ids))}",
            )
        non_pending = [o.id for o in orders if o.status != OrderStatus.PENDING.value]
        if non_pending:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Only PENDING orders can be routed. Non-pending: {non_pending}",
            )
    else:
        orders = db.query(Order).filter(Order.status == OrderStatus.PENDING.value).all()

    # 2. Fetch and validate available fleet riders
    if request.rider_ids:
        riders = db.query(Rider).filter(Rider.id.in_(request.rider_ids)).all()
        found_rider_ids = {r.id for r in riders}
        missing_riders = set(request.rider_ids) - found_rider_ids
        if missing_riders:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Riders not found: {sorted(list(missing_riders))}",
            )
    else:
        riders = db.query(Rider).filter(Rider.is_available.is_(True)).all()

    if not riders:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No available fleet riders available to serve delivery batches.",
        )

    if not orders:
        return RoutesPreviewResult(
            batches=[],
            summary={
                "total_batches": 0,
                "routeable_batches_count": 0,
                "total_route_candidates_evaluated": 0,
                "aco_vs_greedy_comparison": {
                    "aco_total_distance_km": 0.0,
                    "aco_total_duration_min": 0.0,
                    "greedy_total_distance_km": 0.0,
                    "greedy_total_duration_min": 0.0,
                    "distance_delta_pct": 0.0,
                    "duration_delta_pct": 0.0,
                },
            },
            preview_mode=True,
            attribution=DEFAULT_ATTRIBUTION,
            traffic_note=DEFAULT_TRAFFIC_NOTE,
        )

    # 3. Configure GA hyperparameters
    ga_cfg = GAConfig()
    if request.ga_config:
        if request.ga_config.population_size is not None:
            ga_cfg.population_size = request.ga_config.population_size
        if request.ga_config.generations is not None:
            ga_cfg.generations = request.ga_config.generations
        if request.ga_config.mutation_rate is not None:
            ga_cfg.mutation_rate = request.ga_config.mutation_rate
        if request.ga_config.crossover_rate is not None:
            ga_cfg.crossover_rate = request.ga_config.crossover_rate
        if request.ga_config.random_seed is not None:
            ga_cfg.random_seed = request.ga_config.random_seed
        if request.ga_config.service_time_seconds is not None:
            ga_cfg.service_time_seconds = request.ga_config.service_time_seconds

    # 4. Configure ACO hyperparameters
    aco_cfg = ACOConfig()
    if request.aco_config:
        if request.aco_config.num_ants is not None:
            aco_cfg.num_ants = request.aco_config.num_ants
        if request.aco_config.max_iterations is not None:
            aco_cfg.max_iterations = request.aco_config.max_iterations
        if request.aco_config.alpha is not None:
            aco_cfg.alpha = request.aco_config.alpha
        if request.aco_config.beta is not None:
            aco_cfg.beta = request.aco_config.beta
        if request.aco_config.evaporation_rate is not None:
            aco_cfg.evaporation_rate = request.aco_config.evaporation_rate
        if request.aco_config.q_deposit is not None:
            aco_cfg.q_deposit = request.aco_config.q_deposit
        if request.aco_config.random_seed is not None:
            aco_cfg.random_seed = request.aco_config.random_seed
        if request.aco_config.service_time_seconds is not None:
            aco_cfg.service_time_seconds = request.aco_config.service_time_seconds
        if request.aco_config.max_candidate_riders is not None:
            aco_cfg.max_candidate_riders = request.aco_config.max_candidate_riders

    # 5. Execute GA batching and ACO routing preview in-process
    try:
        ga_comparison = GABatchingEngine.optimize_batches(
            orders=orders,
            riders=riders,
            reference_time=now,
            config=ga_cfg,
        )

        routes_result = ACORoutingEngine.optimize_batches_routes(
            batches=ga_comparison.ga_solution.batches,
            all_orders=orders,
            all_riders=riders,
            reference_time=now,
            config=aco_cfg,
        )
        return routes_result
    except NetworkUnavailableError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Road network unavailable for route optimization: {str(e)}",
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )
    except Exception as e:
        logger.exception("Unexpected error during route optimization preview: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Route optimization failed: {str(e)}",
        )


@router.post(
    "/dispatch/preview",
    response_model=DispatchPreviewResult,
    status_code=status.HTTP_200_OK,
    summary="Preview Integrated RL Fleet Dispatch & Baseline Comparison",
    description="Executes end-to-end in-process optimization (Fuzzy Urgency -> GA Batching -> ACO Route Candidates -> RL Dispatch Assignment). Evaluates sequential rider assignments, prevents conflicting overlapping schedules, respects capacity and deadlines, and compares against 3 baseline policies without persisting dispatch assignments or altering database records.",
)
def preview_dispatch(
    request: DispatchOptimizationPreviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_dispatcher),
):
    now = request.reference_time or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    # 1. Fetch and validate candidate orders
    if request.order_ids:
        orders = db.query(Order).filter(Order.id.in_(request.order_ids)).all()
        found_ids = {o.id for o in orders}
        missing_ids = set(request.order_ids) - found_ids
        if missing_ids:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Orders not found: {sorted(list(missing_ids))}",
            )
        non_pending = [o.id for o in orders if o.status != OrderStatus.PENDING.value]
        if non_pending:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Only PENDING orders can be dispatched. Non-pending: {non_pending}",
            )
    else:
        orders = db.query(Order).filter(Order.status == OrderStatus.PENDING.value).all()

    # 2. Fetch and validate available fleet riders
    if request.rider_ids:
        riders = db.query(Rider).filter(Rider.id.in_(request.rider_ids)).all()
        found_rider_ids = {r.id for r in riders}
        missing_riders = set(request.rider_ids) - found_rider_ids
        if missing_riders:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Riders not found: {sorted(list(missing_riders))}",
            )
    else:
        riders = db.query(Rider).filter(Rider.is_available.is_(True)).all()

    if not riders:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No available fleet riders available for dispatch assignment.",
        )

    if not orders:
        return DispatchPreviewResult(
            assignments=[],
            unassigned_batches=[],
            rider_workloads=[],
            summary={
                "total_candidate_batches": 0,
                "assigned_batches_count": 0,
                "unassigned_batches_count": 0,
                "percentage_batches_assigned": 0.0,
                "total_distance_km": 0.0,
                "total_duration_minutes": 0.0,
                "all_assignments_deadline_feasible": True,
                "selected_policy": request.policy_choice,
                "inference_time_ms": 0.0,
            },
            baseline_comparisons={},
            policy_metadata={},
            preview_mode=True,
            attribution=DEFAULT_ATTRIBUTION,
            traffic_note=DEFAULT_TRAFFIC_NOTE,
        )

    # 3. Configure GA & ACO hyperparameters
    ga_cfg = GAConfig()
    if request.ga_config:
        if request.ga_config.population_size is not None:
            ga_cfg.population_size = request.ga_config.population_size
        if request.ga_config.generations is not None:
            ga_cfg.generations = request.ga_config.generations
        if request.ga_config.mutation_rate is not None:
            ga_cfg.mutation_rate = request.ga_config.mutation_rate
        if request.ga_config.crossover_rate is not None:
            ga_cfg.crossover_rate = request.ga_config.crossover_rate
        if request.ga_config.random_seed is not None:
            ga_cfg.random_seed = request.ga_config.random_seed
        if request.ga_config.service_time_seconds is not None:
            ga_cfg.service_time_seconds = request.ga_config.service_time_seconds

    aco_cfg = ACOConfig()
    if request.aco_config:
        if request.aco_config.num_ants is not None:
            aco_cfg.num_ants = request.aco_config.num_ants
        if request.aco_config.max_iterations is not None:
            aco_cfg.max_iterations = request.aco_config.max_iterations
        if request.aco_config.alpha is not None:
            aco_cfg.alpha = request.aco_config.alpha
        if request.aco_config.beta is not None:
            aco_cfg.beta = request.aco_config.beta
        if request.aco_config.evaporation_rate is not None:
            aco_cfg.evaporation_rate = request.aco_config.evaporation_rate
        if request.aco_config.q_deposit is not None:
            aco_cfg.q_deposit = request.aco_config.q_deposit
        if request.aco_config.random_seed is not None:
            aco_cfg.random_seed = request.aco_config.random_seed
        if request.aco_config.service_time_seconds is not None:
            aco_cfg.service_time_seconds = request.aco_config.service_time_seconds
        if request.aco_config.max_candidate_riders is not None:
            aco_cfg.max_candidate_riders = request.aco_config.max_candidate_riders

    # 4. Run RLDispatchService pipeline
    try:
        result = RLDispatchService.run_dispatch_pipeline(
            orders=orders,
            riders=riders,
            reference_time=now,
            policy_choice=request.policy_choice,
            ga_config=ga_cfg,
            aco_config=aco_cfg,
            model_path=request.model_path,
        )

        # Generate unique draft preview identifier and persist draft
        preview_id = f"DRAFT-{uuid.uuid4().hex[:12].upper()}"
        expires_at = now + timedelta(minutes=settings.DISPATCH_DRAFT_EXPIRY_MINUTES)
        result.preview_id = preview_id
        result.expires_at = expires_at

        # Save draft snapshot to SQLite
        try:
            draft = DispatchDraft(
                id=preview_id,
                created_at=now,
                expires_at=expires_at,
                is_committed=False,
                policy_name=result.summary.get("selected_policy", request.policy_choice),
                snapshot_json=result.model_dump_json(),
            )
            db.add(draft)
            db.commit()
        except Exception as draft_err:
            logger.warning("Could not persist dispatch draft: %s", draft_err)
            db.rollback()

        return result
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )
    except NetworkUnavailableError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Road network unavailable for dispatch preview: {str(e)}",
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )
    except Exception as e:
        logger.exception("Unexpected error during dispatch preview: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Dispatch preview failed: {str(e)}",
        )


@router.post(
    "/dispatch/commit",
    response_model=DispatchCommitResponse,
    status_code=status.HTTP_200_OK,
    summary="Transactionally commit approved assignments from a validated dispatch draft plan.",
    description="Validates draft expiry, rider availability, order statuses, capacities, compatibility, and precedence before transactionally persisting Batch, Route, and BatchOrder records.",
)
def commit_dispatch_plan(
    request: DispatchCommitRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_dispatcher),
):
    """Commit a previously reviewed dispatch plan draft into operational records."""
    # 1. Look up draft
    draft = db.get(DispatchDraft, request.preview_id)
    if not draft:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dispatch draft '{request.preview_id}' not found.",
        )

    # 2. Check if already committed (idempotency guard)
    if draft.is_committed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Dispatch draft '{request.preview_id}' was already committed at {draft.committed_at.isoformat() if draft.committed_at else 'unknown'}.",
        )

    # 3. Check expiration
    now_utc = datetime.now(timezone.utc)
    draft_exp = draft.expires_at
    if draft_exp.tzinfo is None:
        draft_exp = draft_exp.replace(tzinfo=timezone.utc)
    if draft_exp < now_utc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Dispatch draft '{request.preview_id}' expired at {draft_exp.isoformat()}. Please generate a fresh preview.",
        )

    # 4. Parse snapshot
    try:
        snapshot = json.loads(draft.snapshot_json)
    except Exception as parse_err:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Corrupted draft snapshot: {str(parse_err)}",
        )

    all_assignments = snapshot.get("assignments", [])
    unassigned_batches = snapshot.get("unassigned_batches", [])

    if request.approved_batch_ids is not None:
        approved_set = set(request.approved_batch_ids)
        assignments_to_commit = [a for a in all_assignments if a["batch_id"] in approved_set]
        if not assignments_to_commit:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="None of the specified 'approved_batch_ids' matched assignments in the draft plan.",
            )
    else:
        assignments_to_commit = all_assignments

    if not assignments_to_commit:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The draft plan contains no feasible assignments to commit.",
        )

    # 5. Independent Pre-Commit Revalidation
    committed_riders = set()
    for a in assignments_to_commit:
        rider_id = a["assigned_rider_id"]
        rider = db.get(Rider, rider_id)
        if not rider:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Rider '{rider_id}' no longer exists in the fleet.",
            )
        if not rider.is_available:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Rider '{rider.display_name}' ({rider.id}) is no longer available.",
            )
        if rider_id in committed_riders:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Conflicting assignment: Rider '{rider.display_name}' cannot be assigned to multiple batches in the same commit.",
            )
        committed_riders.add(rider_id)

        active_route = (
            db.query(Route)
            .filter(Route.rider_id == rider.id, Route.status == RouteStatus.ASSIGNED.value)
            .first()
        )
        if active_route:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Rider '{rider.display_name}' already has an active committed route '{active_route.id}'.",
            )

        order_objs = []
        for oid in a["order_ids"]:
            ord_obj = db.get(Order, oid)
            if not ord_obj:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Order '{oid}' not found in database.",
                )
            if ord_obj.status != OrderStatus.PENDING.value:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Order '{oid}' is no longer PENDING (current status: '{ord_obj.status}').",
                )
            order_objs.append(ord_obj)

        # Revalidate cumulative capacities
        batch_weight = sum(o.weight_kg for o in order_objs)
        batch_pkgs = sum(o.package_count for o in order_objs)
        if batch_weight > rider.weight_capacity_kg:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Batch '{a['batch_id']}' weight ({batch_weight:.1f} kg) exceeds rider capacity ({rider.weight_capacity_kg:.1f} kg).",
            )
        if batch_pkgs > rider.package_count_capacity:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Batch '{a['batch_id']}' packages ({batch_pkgs}) exceeds rider capacity ({rider.package_count_capacity}).",
            )

        # Revalidate package compatibility
        pkg_types = {o.package_type.upper() for o in order_objs}
        if "MEDICAL" in pkg_types and "PERISHABLE" in pkg_types:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Batch '{a['batch_id']}' combines incompatible MEDICAL and PERISHABLE packages.",
            )

        # Revalidate route precedence (pickup strictly precedes delivery)
        stops = a.get("stops", [])
        pickup_indices = {s["order_id"]: s["stop_index"] for s in stops if s.get("stop_type") == "PICKUP"}
        delivery_indices = {s["order_id"]: s["stop_index"] for s in stops if s.get("stop_type") == "DELIVERY"}
        for oid in a["order_ids"]:
            if oid in pickup_indices and oid in delivery_indices:
                if pickup_indices[oid] >= delivery_indices[oid]:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Precedence violation for order '{oid}' in batch '{a['batch_id']}': pickup stop ({pickup_indices[oid]}) must precede delivery ({delivery_indices[oid]}).",
                    )

    # 6. Atomic Transactional Persistence
    try:
        committed_infos: List[CommittedBatchInfo] = []
        total_orders_dispatched = 0

        for a in assignments_to_commit:
            b_id = a["batch_id"]
            # Ensure unique Batch ID in database
            existing_b = db.get(Batch, b_id)
            if existing_b:
                b_id = f"{b_id}-{uuid.uuid4().hex[:6].upper()}"

            batch_rec = Batch(
                id=b_id,
                status=BatchStatus.ASSIGNED.value,
                objective_score=float(a.get("distance_km", 0.0)),
                created_at=now_utc,
            )
            db.add(batch_rec)
            db.flush()

            for oid in a["order_ids"]:
                bo = BatchOrder(batch_id=b_id, order_id=oid)
                db.add(bo)
                ord_obj = db.get(Order, oid)
                ord_obj.status = OrderStatus.DISPATCHED.value
                total_orders_dispatched += 1

            r_id = f"ROUTE-{b_id}"
            route_rec = Route(
                id=r_id,
                batch_id=b_id,
                rider_id=a["assigned_rider_id"],
                ordered_stops=json.dumps(a.get("stops", [])),
                estimated_distance_m=float(a.get("distance_km", 0.0)) * 1000.0,
                estimated_duration_s=float(a.get("duration_minutes", 0.0)) * 60.0,
                status=RouteStatus.ASSIGNED.value,
                created_at=now_utc,
            )
            db.add(route_rec)

            rider_obj = db.get(Rider, a["assigned_rider_id"])
            rider_obj.is_available = False

            committed_infos.append(
                CommittedBatchInfo(
                    batch_id=b_id,
                    assigned_rider_id=a["assigned_rider_id"],
                    assigned_rider_name=a["assigned_rider_name"],
                    route_id=r_id,
                    order_ids=a["order_ids"],
                    total_distance_km=float(a.get("distance_km", 0.0)),
                    total_duration_minutes=float(a.get("duration_minutes", 0.0)),
                    stops_count=len(a.get("stops", [])),
                )
            )

        draft.is_committed = True
        draft.committed_at = now_utc

        db.commit()

        return DispatchCommitResponse(
            status="committed",
            preview_id=draft.id,
            committed_at=now_utc,
            committed_batches=committed_infos,
            total_orders_dispatched=total_orders_dispatched,
            uncommitted_unassigned_batches=unassigned_batches,
            message=f"Successfully committed {len(committed_infos)} batches ({total_orders_dispatched} orders) to operational dispatch.",
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as tx_err:
        db.rollback()
        logger.exception("Transactional commit error: %s", tx_err)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Transactional commit failed: {str(tx_err)}",
        )


