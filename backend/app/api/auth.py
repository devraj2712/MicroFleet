import logging
import uuid
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.core.auth import get_current_user, verify_firebase_token
from backend.app.core.config import settings
from backend.app.core.database import get_db
from backend.app.models.entities import Merchant, Rider, User, UserRole
from backend.app.schemas.schemas import (
    AdminProvisionRequest,
    AuthTokenResponse,
    LoginRequest,
    RegisterRequest,
    UserResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication & User Profiles"])


@router.post(
    "/register",
    response_model=AuthTokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new merchant or rider profile.",
)
def register(
    request: RegisterRequest,
    db: Session = Depends(get_db),
):
    """Register a new user account with role MERCHANT or RIDER.
    
    Self-registration as DISPATCHER or ADMIN is strictly forbidden.
    """
    req_role = request.role.upper()
    if req_role not in [UserRole.MERCHANT.value, UserRole.RIDER.value]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Self-registration is only permitted for 'MERCHANT' or 'RIDER' roles. Dispatcher/Admin accounts must be provisioned administratively.",
        )

    # Check for existing user email
    existing = db.query(User).filter(User.email == request.email.strip().lower()).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"User with email '{request.email}' already exists.",
        )

    now = datetime.now(timezone.utc)
    user_id = f"USR-{uuid.uuid4().hex[:10].upper()}"
    merchant_id: Optional[str] = None
    rider_id: Optional[str] = None

    if req_role == UserRole.MERCHANT.value:
        # Create merchant entity
        merchant_id = f"M-{uuid.uuid4().hex[:8].upper()}"
        m_name = request.display_name or f"Merchant {request.email.split('@')[0]}"
        p_lat = request.pickup_latitude if request.pickup_latitude is not None else 19.0596
        p_lon = request.pickup_longitude if request.pickup_longitude is not None else 72.8295

        merchant = Merchant(
            id=merchant_id,
            name=m_name,
            merchant_type=request.merchant_type or "Retail",
            pickup_latitude=p_lat,
            pickup_longitude=p_lon,
            is_active=True,
            created_at=now,
        )
        db.add(merchant)

    elif req_role == UserRole.RIDER.value:
        # Create rider entity awaiting approval (is_available=False initially)
        rider_id = f"R-{uuid.uuid4().hex[:8].upper()}"
        r_name = request.display_name or f"Rider {request.email.split('@')[0]}"

        rider = Rider(
            id=rider_id,
            display_name=r_name,
            current_latitude=19.0550,
            current_longitude=72.8350,
            weight_capacity_kg=request.weight_capacity_kg or 20.0,
            package_count_capacity=request.package_count_capacity or 10,
            is_available=True,  # Activated for development testing
            created_at=now,
        )
        db.add(rider)

    user = User(
        id=user_id,
        email=request.email.strip().lower(),
        role=req_role,
        merchant_id=merchant_id,
        rider_id=rider_id,
        is_active=True,
        created_at=now,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = f"dev-token:{user.id}" if settings.AUTH_MODE == "development" else "registered-pending-firebase-login"

    return AuthTokenResponse(
        access_token=token,
        token_type="Bearer",
        auth_mode=settings.AUTH_MODE,
        user=UserResponse.model_validate(user),
    )


@router.post(
    "/login",
    response_model=AuthTokenResponse,
    summary="Authenticate and retrieve user profile with access token.",
)
def login(
    request: LoginRequest,
    db: Session = Depends(get_db),
):
    """Authenticate user.
    
    In 'development' mode:
      - Accepts email (and optional password) or pre-seeded demo credentials.
    In 'firebase' mode:
      - Requires a valid Firebase ID token in 'id_token' or Authorization header.
    """
    auth_mode = settings.AUTH_MODE.lower()

    if auth_mode == "firebase":
        if not request.id_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Firebase mode requires 'id_token' in request body.",
            )
        decoded = verify_firebase_token(request.id_token)
        uid = decoded.get("uid")
        email = decoded.get("email")

        user = db.query(User).filter(User.id == uid).first()
        if not user and email:
            user = db.query(User).filter(User.email == email).first()
            if user:
                user.id = uid
                db.commit()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No authorized backend profile found for Firebase UID '{uid}'. Please register first.",
            )

        return AuthTokenResponse(
            access_token=request.id_token,
            token_type="Bearer",
            auth_mode="firebase",
            user=UserResponse.model_validate(user),
        )

    elif auth_mode == "development":
        if not request.email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Development login requires 'email' (e.g. 'dispatcher@microfleet.dev', 'merchant@microfleet.dev', 'rider@microfleet.dev').",
            )
        clean_email = request.email.strip().lower()
        user = db.query(User).filter(User.email == clean_email).first()

        if not user:
            # Check by user ID as convenience
            user = db.query(User).filter(User.id == request.email.strip()).first()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Development user '{request.email}' not found. Pre-seeded users: 'merchant@microfleet.dev', 'rider@microfleet.dev', 'dispatcher@microfleet.dev', 'admin@microfleet.dev'.",
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive.",
            )

        return AuthTokenResponse(
            access_token=f"dev-token:{user.id}",
            token_type="Bearer",
            auth_mode="development",
            user=UserResponse.model_validate(user),
        )

    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unsupported AUTH_MODE: '{auth_mode}'",
        )


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Retrieve the current authenticated user's profile.",
)
def get_me(
    current_user: User = Depends(get_current_user),
):
    """Return the authenticated user profile."""
    return UserResponse.model_validate(current_user)


@router.post(
    "/provision-admin",
    response_model=UserResponse,
    summary="Administratively provision a Dispatcher or Admin account using the secret key.",
)
def provision_admin(
    request: AdminProvisionRequest,
    db: Session = Depends(get_db),
):
    """Explicit documented administrative provisioning method for dispatcher/admin accounts."""
    if request.admin_secret != settings.ADMIN_PROVISION_SECRET:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid administrative provisioning secret key.",
        )

    clean_email = request.email.strip().lower()
    user = db.query(User).filter(User.email == clean_email).first()
    now = datetime.now(timezone.utc)

    if not user:
        user = User(
            id=f"USR-{uuid.uuid4().hex[:10].upper()}",
            email=clean_email,
            role=request.role.upper(),
            is_active=True,
            created_at=now,
        )
        db.add(user)
    else:
        user.role = request.role.upper()
        user.is_active = True

    db.commit()
    db.refresh(user)
    logger.info("Provisioned user '%s' with role '%s'", user.email, user.role)
    return UserResponse.model_validate(user)
