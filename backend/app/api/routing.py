import logging
from fastapi import APIRouter, HTTPException, status

from backend.app.intelligence.osm.osm_service import (
    CoordinateOutOfBoundsError,
    DestinationUnreachableError,
    NetworkUnavailableError,
    OSMService,
    SnapDistanceExceededError,
)
from backend.app.schemas.schemas import (
    RouteEstimateRequest,
    RouteEstimateResponse,
    RoutingMatrixRequest,
    RoutingMatrixResponse,
    RoutingStatusResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/routing", tags=["Routing & Geospatial"])


@router.get(
    "/status",
    response_model=RoutingStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Road Network Status",
    description="Returns availability, coverage bounds, node/edge counts, and travel-time model metadata of the cached OpenStreetMap road network.",
)
def get_routing_status():
    return OSMService.get_status()


@router.post(
    "/estimate",
    response_model=RouteEstimateResponse,
    status_code=status.HTTP_200_OK,
    summary="Estimate Route Distance & Travel Time",
    description="Calculates road network route, distance, estimated travel time, and ordered coordinate geometry between origin and destination.",
)
def estimate_route(request: RouteEstimateRequest):
    try:
        return OSMService.estimate_route(
            orig_lat=request.origin.latitude,
            orig_lon=request.origin.longitude,
            dest_lat=request.destination.latitude,
            dest_lon=request.destination.longitude,
            weight=request.weight,
        )
    except NetworkUnavailableError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Geospatial routing service unavailable: {str(e)}",
        )
    except (CoordinateOutOfBoundsError, SnapDistanceExceededError) as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )
    except DestinationUnreachableError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except Exception as e:
        logger.exception("Unexpected error during route estimation: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Route calculation failed: {str(e)}",
        )


@router.post(
    "/matrix",
    response_model=RoutingMatrixResponse,
    status_code=status.HTTP_200_OK,
    summary="Compute Pairwise Distance & Duration Matrix",
    description="Calculates NxN road-network distance and travel-time matrices for up to 50 identified locations, maintaining exact input ordering for GA and ACO batch optimization.",
)
def compute_matrix(request: RoutingMatrixRequest):
    try:
        return OSMService.compute_matrix(
            locations=request.locations,
            weight=request.weight,
        )
    except NetworkUnavailableError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Geospatial routing service unavailable: {str(e)}",
        )
    except (CoordinateOutOfBoundsError, SnapDistanceExceededError, ValueError) as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )
    except Exception as e:
        logger.exception("Unexpected error during matrix calculation: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Matrix calculation failed: {str(e)}",
        )
