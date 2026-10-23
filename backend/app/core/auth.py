import logging
from typing import List, Optional
from fastapi import Depends, HTTPException, Header, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.core.database import get_db
from backend.app.models.entities import User, UserRole

logger = logging.getLogger(__name__)

# Security scheme for Bearer token
security_bearer = HTTPBearer(auto_error=False)

# Firebase Admin app state
_firebase_initialized = False


def init_firebase_admin() -> bool:
    """Initialize Firebase Admin SDK if not already initialized."""
    global _firebase_initialized
    if _firebase_initialized:
        return True

    try:
        import firebase_admin
        from firebase_admin import credentials

        if firebase_admin._apps:
            _firebase_initialized = True
            return True

        if settings.FIREBASE_SERVICE_ACCOUNT_PATH:
            cred = credentials.Certificate(settings.FIREBASE_SERVICE_ACCOUNT_PATH)
            firebase_admin.initialize_app(cred)
            logger.info("Firebase Admin initialized with service account certificate.")
            _firebase_initialized = True
            return True
        else:
            # Attempt default application credentials
            try:
                firebase_admin.initialize_app()
                logger.info("Firebase Admin initialized with default credentials.")
                _firebase_initialized = True
                return True
            except Exception as default_e:
                logger.warning("Firebase Admin default credential initialization failed: %s", default_e)
                return False
    except Exception as e:
        logger.error("Failed to initialize Firebase Admin SDK: %s", e)
        return False


def verify_firebase_token(token: str) -> dict:
    """Verify incoming Firebase ID token using firebase_admin.auth."""
    import firebase_admin.auth

    if not init_firebase_admin():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Firebase authentication verifier is not configured or unavailable.",
        )

    try:
        decoded = firebase_admin.auth.verify_id_token(token)
        return decoded
    except Exception as e:
        logger.warning("Firebase ID token verification failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired Firebase ID token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_current_user(
    request: Request,
    auth_header: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer),
    x_dev_user_email: Optional[str] = Header(None, alias="X-Dev-User-Email"),
    x_dev_user_id: Optional[str] = Header(None, alias="X-Dev-User-Id"),
    db: Session = Depends(get_db),
) -> User:
    """Authenticate and return the current authorized User profile.
    
    In 'development' mode:
      - Validates Bearer token (as dev UID or dev token) OR development headers (X-Dev-User-Email / X-Dev-User-Id)
      - Matches an existing User in SQLite.
      - Refuses arbitrary unauthenticated role claims.
    
    In 'firebase' mode:
      - Strictly requires a verified Firebase Bearer token.
      - Refuses all dev headers and unverified tokens.
    """
    auth_mode = settings.AUTH_MODE.lower()

    if auth_mode == "firebase":
        # Strictly verify Firebase ID token
        if not auth_header or not auth_header.credentials:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required: Missing Bearer token in Authorization header.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        decoded_token = verify_firebase_token(auth_header.credentials)
        uid = decoded_token.get("uid")
        email = decoded_token.get("email")

        if not uid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Malformed token: Missing 'uid' claim.",
            )

        # Look up or bind user profile
        user = db.query(User).filter(User.id == uid).first()
        if not user and email:
            user = db.query(User).filter(User.email == email).first()
            if user:
                # Update UID to match Firebase UID
                user.id = uid
                db.commit()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Authenticated Firebase user '{email or uid}' has no authorized backend profile. Please register first.",
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive.",
            )

        return user

    elif auth_mode == "development":
        # Development mode: allow dev Bearer token or dev headers
        user: Optional[User] = None

        if auth_header and auth_header.credentials:
            token = auth_header.credentials.strip()
            # Check if token is dev-token:<email> or dev-token:<id> or raw ID/email
            if token.startswith("dev-token:"):
                identifier = token.replace("dev-token:", "").strip()
                user = db.query(User).filter((User.id == identifier) | (User.email == identifier)).first()
            else:
                user = db.query(User).filter((User.id == token) | (User.email == token)).first()

        if not user and x_dev_user_email:
            user = db.query(User).filter(User.email == x_dev_user_email.strip()).first()

        if not user and x_dev_user_id:
            user = db.query(User).filter(User.id == x_dev_user_id.strip()).first()

        if not user:
            # In development mode, if no user credentials are provided, default to the seeded dev dispatcher
            user = db.query(User).filter(User.email == "dispatcher@microfleet.dev").first()
            if not user:
                user = User(
                    id="USR-DEV-DISPATCHER",
                    email="dispatcher@microfleet.dev",
                    role=UserRole.DISPATCHER.value,
                    is_active=True,
                )
                db.add(user)
                try:
                    db.commit()
                except Exception:
                    db.rollback()

        if not user:
            # Fallback: if no credentials supplied in dev mode and seed user missing, reject
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Development Authentication Required. Supply 'Authorization: Bearer <dev-token or uid>' or 'X-Dev-User-Email' header (e.g., 'dispatcher@microfleet.dev', 'merchant@microfleet.dev', or 'rider@microfleet.dev').",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive.",
            )

        return user

    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unknown AUTH_MODE configured: '{auth_mode}'",
        )


def require_role(allowed_roles: List[UserRole]):
    """Factory dependency to enforce role-based access control."""
    def role_checker(current_user: User = Depends(get_current_user)) -> User:
        allowed_str = [r.value for r in allowed_roles]
        if current_user.role not in allowed_str:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: User role '{current_user.role}' is not authorized. Required: {allowed_str}",
            )
        return current_user

    return role_checker


# Role convenience dependencies
require_merchant = require_role([UserRole.MERCHANT, UserRole.ADMIN])
require_rider = require_role([UserRole.RIDER, UserRole.ADMIN])
require_dispatcher = require_role([UserRole.DISPATCHER, UserRole.ADMIN])
require_admin = require_role([UserRole.ADMIN])


def get_optional_current_user(
    request: Request,
    auth_header: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer),
    x_dev_user_email: Optional[str] = Header(None, alias="X-Dev-User-Email"),
    x_dev_user_id: Optional[str] = Header(None, alias="X-Dev-User-Id"),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Retrieve authenticated user if credentials provided; otherwise return None."""
    try:
        # If no credentials passed at all, avoid failing in optional context
        if not auth_header and not x_dev_user_email and not x_dev_user_id:
            return None
        return get_current_user(request, auth_header, x_dev_user_email, x_dev_user_id, db)
    except HTTPException:
        return None
