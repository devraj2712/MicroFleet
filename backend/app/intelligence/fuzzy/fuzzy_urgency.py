import enum
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

from pydantic import BaseModel, Field

from backend.app.intelligence.osm.osm_service import (
    CoordinateOutOfBoundsError,
    DestinationUnreachableError,
    NetworkUnavailableError,
    OSMService,
    SnapDistanceExceededError,
)

logger = logging.getLogger(__name__)


class UrgencyCategory(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class FuzzyUrgencyResult(BaseModel):
    """Complete interpretable urgency score and diagnostic explanation for a delivery order."""
    order_id: str
    urgency_score: float = Field(..., ge=0.0, le=100.0, description="Defuzzified urgency score from 0.0 to 100.0")
    urgency_category: UrgencyCategory
    solo_travel_time_seconds: float
    solo_distance_meters: Optional[float] = None
    deadline_slack_minutes: float
    waiting_time_minutes: float
    priority_score: float
    contributing_rules: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


def trimf(x: float, a: float, b: float, c: float) -> float:
    """Triangular membership function with peak at b."""
    if x <= a or x >= c:
        return 0.0
    if a < x <= b:
        return (x - a) / (b - a) if b > a else 1.0
    return (c - x) / (c - b) if c > b else 1.0


def trapmf(x: float, a: float, b: float, c: float, d: float) -> float:
    """Trapezoidal membership function with flat plateau between b and c."""
    if x < b:
        if a == float("-inf"):
            return 1.0
        if x <= a:
            return 0.0
        return (x - a) / (b - a) if b > a else 1.0
    elif b <= x <= c:
        return 1.0
    else:  # x > c
        if d == float("inf"):
            return 1.0
        if x >= d:
            return 0.0
        return (d - x) / (d - c) if d > c else 1.0


class FuzzyUrgencyEngine:
    """Mamdani-style Fuzzy Inference System for interpretable delivery order urgency calculation.

    Inputs:
      1. Deadline Slack (minutes): remaining time minus solo road travel time and service allowance.
      2. Order Waiting Time (minutes): elapsed time since creation.
      3. Priority Score [0.0, 1.0]: weighted synthesis of customer priority, merchant priority, and package sensitivity.

    Output:
      Urgency Score [0.0, 100.0] defuzzified via Centroid (Center of Gravity).
    """

    DEFAULT_SERVICE_TIME_SEC: float = 180.0  # 3 minutes for pickup + drop-off handling

    # Customer Priority Weights
    CUSTOMER_PRIORITY_MAP: Dict[str, float] = {
        "VIP": 1.0,
        "PREMIUM": 0.7,
        "STANDARD": 0.4,
    }

    # Package Sensitivity Weights based on explicit domain requirements
    PACKAGE_TYPE_MAP: Dict[str, float] = {
        "MEDICAL": 1.0,      # Urgent prescription pharmaceuticals
        "PERISHABLE": 0.8,   # Temperature sensitive confectioneries / fresh vegetables
        "PARCEL": 0.4,       # Standard retail parcel
    }

    @classmethod
    def compute_priority_score(
        cls,
        customer_priority: str,
        merchant_priority: int,
        package_type: str,
        handling_requirements: Optional[str] = None,
    ) -> float:
        """Synthesize customer priority, merchant priority, and package sensitivity into a [0.0, 1.0] score."""
        c_score = cls.CUSTOMER_PRIORITY_MAP.get(str(customer_priority).upper(), 0.4)
        m_score = min(max(float(merchant_priority), 1.0), 10.0) / 10.0
        p_score = cls.PACKAGE_TYPE_MAP.get(str(package_type).upper(), 0.4)

        # Detect explicit urgent handling modifiers if present in existing handling field
        handling_text = (handling_requirements or "").lower()
        if "urgent" in handling_text or "life" in handling_text:
            p_score = min(1.0, p_score + 0.15)
        elif "temperature" in handling_text or "fragile" in handling_text:
            p_score = min(1.0, p_score + 0.05)

        # Weighted combination: 45% customer, 25% merchant, 30% package sensitivity
        combined = 0.45 * c_score + 0.25 * m_score + 0.30 * p_score
        return round(min(max(combined, 0.0), 1.0), 4)

    @classmethod
    def evaluate_membership(
        cls,
        deadline_slack_min: float,
        waiting_time_min: float,
        priority_score: float,
    ) -> Dict[str, Dict[str, float]]:
        """Evaluate membership degrees for all linguistic variables."""
        # 1. Deadline Slack terms
        # Overdue: slack <= 0 (flat at 1.0 below 0, falls to 0 at 5m)
        mu_slack = {
            "OVERDUE": trapmf(deadline_slack_min, float("-inf"), float("-inf"), 0.0, 5.0),
            "CRITICAL": trimf(deadline_slack_min, 0.0, 10.0, 25.0),
            "TIGHT": trimf(deadline_slack_min, 15.0, 35.0, 60.0),
            "COMFORTABLE": trapmf(deadline_slack_min, 45.0, 75.0, float("inf"), float("inf")),
        }

        # 2. Waiting Time terms
        mu_wait = {
            "SHORT": trapmf(waiting_time_min, 0.0, 0.0, 10.0, 25.0),
            "MEDIUM": trimf(waiting_time_min, 15.0, 35.0, 60.0),
            "LONG": trapmf(waiting_time_min, 45.0, 75.0, float("inf"), float("inf")),
        }

        # 3. Priority Score terms
        mu_prio = {
            "LOW": trapmf(priority_score, 0.0, 0.0, 0.30, 0.50),
            "MEDIUM": trimf(priority_score, 0.35, 0.55, 0.75),
            "HIGH": trapmf(priority_score, 0.65, 0.85, 1.0, 1.0),
        }

        return {
            "slack": mu_slack,
            "wait": mu_wait,
            "prio": mu_prio,
        }

    @classmethod
    def defuzzify_centroid(cls, aggregated_output: List[float], step: float = 1.0) -> float:
        """Centroid (Center of Gravity) defuzzification over universe [0, 100]."""
        numerator = 0.0
        denominator = 0.0
        for i, mu in enumerate(aggregated_output):
            x = i * step
            numerator += x * mu
            denominator += mu

        if denominator == 0.0:
            return 50.0  # Fallback to center if no rule fired
        return round(numerator / denominator, 2)

    @classmethod
    def infer_urgency(
        cls,
        deadline_slack_min: float,
        waiting_time_min: float,
        priority_score: float,
    ) -> Tuple[float, UrgencyCategory, List[str]]:
        """Execute Mamdani inference and centroid defuzzification."""
        memberships = cls.evaluate_membership(deadline_slack_min, waiting_time_min, priority_score)
        s = memberships["slack"]
        w = memberships["wait"]
        p = memberships["prio"]

        # Output universe [0, 100] sampled with step 1.0 (101 points)
        universe = [float(i) for i in range(101)]

        # Output membership functions
        mu_out_low = [trapmf(u, 0.0, 0.0, 20.0, 35.0) for u in universe]
        mu_out_med = [trimf(u, 25.0, 45.0, 65.0) for u in universe]
        mu_out_high = [trimf(u, 55.0, 75.0, 88.0) for u in universe]
        mu_out_crit = [trapmf(u, 80.0, 92.0, 100.0, 100.0) for u in universe]

        # Documented Mamdani Rule Base: (strength, output_membership_vector, description)
        rules: List[Tuple[float, List[float], str]] = [
            (
                s["OVERDUE"],
                mu_out_crit,
                "R1: IF deadline is OVERDUE THEN urgency is CRITICAL",
            ),
            (
                s["CRITICAL"],
                mu_out_crit,
                "R2: IF deadline is CRITICAL THEN urgency is CRITICAL",
            ),
            (
                min(s["TIGHT"], p["HIGH"]),
                mu_out_crit,
                "R3: IF deadline is TIGHT AND priority is HIGH THEN urgency is CRITICAL",
            ),
            (
                min(s["TIGHT"], w["LONG"]),
                mu_out_high,
                "R4: IF deadline is TIGHT AND waiting_time is LONG THEN urgency is HIGH",
            ),
            (
                min(s["TIGHT"], w["MEDIUM"]),
                mu_out_high,
                "R5: IF deadline is TIGHT AND waiting_time is MEDIUM THEN urgency is HIGH",
            ),
            (
                min(s["TIGHT"], w["SHORT"]),
                mu_out_med,
                "R6: IF deadline is TIGHT AND waiting_time is SHORT THEN urgency is MEDIUM",
            ),
            (
                min(s["COMFORTABLE"], p["HIGH"], w["LONG"]),
                mu_out_high,
                "R7: IF deadline is COMFORTABLE AND priority is HIGH AND waiting_time is LONG THEN urgency is HIGH",
            ),
            (
                min(s["COMFORTABLE"], p["HIGH"]),
                mu_out_med,
                "R8: IF deadline is COMFORTABLE AND priority is HIGH THEN urgency is MEDIUM",
            ),
            (
                min(s["COMFORTABLE"], p["MEDIUM"]),
                mu_out_med,
                "R9: IF deadline is COMFORTABLE AND priority is MEDIUM THEN urgency is MEDIUM",
            ),
            (
                min(s["COMFORTABLE"], p["LOW"], w["SHORT"]),
                mu_out_low,
                "R10: IF deadline is COMFORTABLE AND priority is LOW AND waiting_time is SHORT THEN urgency is LOW",
            ),
            (
                min(s["COMFORTABLE"], p["LOW"], w["MEDIUM"]),
                mu_out_low,
                "R11: IF deadline is COMFORTABLE AND priority is LOW AND waiting_time is MEDIUM THEN urgency is LOW",
            ),
            (
                min(s["COMFORTABLE"], w["LONG"]),
                mu_out_med,
                "R12: IF deadline is COMFORTABLE AND waiting_time is LONG THEN urgency is MEDIUM",
            ),
            (
                min(p["HIGH"], w["LONG"]),
                mu_out_high,
                "R13: IF priority is HIGH AND waiting_time is LONG THEN urgency is HIGH",
            ),
        ]

        # Aggregate output using Mamdani min implication and max aggregation
        aggregated = [0.0] * len(universe)
        contributing_rules: List[str] = []

        for firing_strength, out_set, rule_desc in rules:
            if firing_strength > 0.02:
                contributing_rules.append(f"{rule_desc} [fire={firing_strength:.2f}]")
                for i in range(len(universe)):
                    implicated = min(firing_strength, out_set[i])
                    if implicated > aggregated[i]:
                        aggregated[i] = implicated

        score = cls.defuzzify_centroid(aggregated)

        # Categorize
        if score < 25.0:
            category = UrgencyCategory.LOW
        elif score < 55.0:
            category = UrgencyCategory.MEDIUM
        elif score < 80.0:
            category = UrgencyCategory.HIGH
        else:
            category = UrgencyCategory.CRITICAL


        return score, category, contributing_rules

    @classmethod
    def score_order(
        cls,
        order: Any,
        reference_time: Optional[datetime] = None,
        service_time_seconds: Optional[float] = None,
    ) -> FuzzyUrgencyResult:
        """Calculate interpretable urgency score for an order entity or dict using road network solo travel time."""
        now = reference_time or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        def _get_val(obj: Any, key: str, default: Any = None) -> Any:
            if isinstance(obj, dict):
                return obj.get(key, default)
            val = getattr(obj, key, None)
            return val if val is not None else default

        order_id = str(_get_val(order, "id", "UNKNOWN_ORDER"))
        deadline = _get_val(order, "delivery_deadline", now)
        created_at = _get_val(order, "created_at", now)

        if isinstance(deadline, str):
            deadline = datetime.fromisoformat(deadline)
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)

        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        p_lat = float(_get_val(order, "pickup_latitude", 0.0))
        p_lon = float(_get_val(order, "pickup_longitude", 0.0))
        d_lat = float(_get_val(order, "delivery_latitude", 0.0))
        d_lon = float(_get_val(order, "delivery_longitude", 0.0))

        c_priority = str(_get_val(order, "customer_priority", "STANDARD"))
        m_priority = int(_get_val(order, "merchant_priority", 1))
        pkg_type = str(_get_val(order, "package_type", "PARCEL"))
        handling = str(_get_val(order, "handling_requirements", ""))


        warnings: List[str] = []
        solo_travel_time_sec = 600.0  # 10 min fallback
        solo_dist_m: Optional[float] = None

        # Calculate solo road route travel time via OSMService
        try:
            route_res = OSMService.estimate_route(
                orig_lat=p_lat,
                orig_lon=p_lon,
                dest_lat=d_lat,
                dest_lon=d_lon,
                weight="travel_time",
            )
            solo_travel_time_sec = float(route_res.duration_seconds)
            solo_dist_m = float(route_res.distance_meters)
        except NetworkUnavailableError as e:
            warnings.append(f"Road network unavailable: {e}. Defaulted solo travel time to {solo_travel_time_sec:.0f}s.")
        except DestinationUnreachableError as e:
            warnings.append(f"Destination unreachable on road network: {e}. Defaulted solo travel time to {solo_travel_time_sec:.0f}s.")
        except (CoordinateOutOfBoundsError, SnapDistanceExceededError) as e:
            warnings.append(f"Coordinate snapping issue: {e}. Defaulted solo travel time to {solo_travel_time_sec:.0f}s.")
        except Exception as e:
            warnings.append(f"Route calculation unexpected error: {e}. Defaulted solo travel time to {solo_travel_time_sec:.0f}s.")

        service_sec = service_time_seconds if service_time_seconds is not None else cls.DEFAULT_SERVICE_TIME_SEC

        # 1. Deadline Slack (minutes)
        total_remaining_sec = (deadline - now).total_seconds()
        slack_sec = total_remaining_sec - solo_travel_time_sec - service_sec
        deadline_slack_min = round(slack_sec / 60.0, 2)

        # 2. Waiting Time (minutes)
        elapsed_sec = max(0.0, (now - created_at).total_seconds())
        waiting_time_min = round(elapsed_sec / 60.0, 2)

        # 3. Priority Score [0.0, 1.0]
        priority_score = cls.compute_priority_score(c_priority, m_priority, pkg_type, handling)

        # Mamdani Inference & Defuzzification
        score, category, rules = cls.infer_urgency(deadline_slack_min, waiting_time_min, priority_score)

        return FuzzyUrgencyResult(
            order_id=order_id,
            urgency_score=score,
            urgency_category=category,
            solo_travel_time_seconds=round(solo_travel_time_sec, 1),
            solo_distance_meters=round(solo_dist_m, 1) if solo_dist_m is not None else None,
            deadline_slack_minutes=deadline_slack_min,
            waiting_time_minutes=waiting_time_min,
            priority_score=priority_score,
            contributing_rules=rules,
            warnings=warnings,
        )
