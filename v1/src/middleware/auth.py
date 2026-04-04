"""
Authentication middleware for WiFi-DensePose API
"""

import logging
import re
import time
from typing import Optional, Dict, Any, Callable
from datetime import UTC, datetime, timedelta

from fastapi import Request, Response, HTTPException, status
from jose import JWTError, jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from src.config.settings import Settings
from src.logger import set_request_context

logger = logging.getLogger(__name__)


PUBLIC_EXACT_PATHS = {
    "/openapi.json",
    "/auth/login",
    "/auth/register",
    "/health/health",
    "/health/ready",
    "/health/live",
    "/health/version",
    "/health/metrics",
    "/api/v1/health",
    "/api/v1/ready",
    "/api/v1/info",
    "/api/v1/status",
    "/api/v1/metrics",
    "/api/v1/pose/current",
    "/api/v1/pose/zones/summary",
    "/api/v1/pose/activities",
    "/api/v1/pose/stats",
    "/api/v1/stream/status",
    "/api/v1/stream/metrics",
    "/api/v1/fp2/status",
    "/api/v1/fp2/current",
    "/api/v1/fp2/entities",
    "/api/v1/fp2/recommended-entity",
}

PUBLIC_PATH_PREFIXES = (
    "/docs",
    "/redoc",
    "/static",
)

PUBLIC_PATH_PATTERNS = (
    re.compile(r"^/api/v1/pose/zones/[^/]+/occupancy$"),
)


def _matches_public_prefix(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(f"{prefix}/")


def is_public_http_path(path: str) -> bool:
    """Return True when the path belongs to the public runtime surface."""
    if path in PUBLIC_EXACT_PATHS:
        return True

    if any(_matches_public_prefix(path, prefix) for prefix in PUBLIC_PATH_PREFIXES):
        return True

    return any(pattern.fullmatch(path) for pattern in PUBLIC_PATH_PATTERNS)


class AuthenticationError(Exception):
    """Authentication error."""
    pass


class AuthorizationError(Exception):
    """Authorization error."""
    pass


def _normalize_authenticated_user(user: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize auth payloads to the user shape expected by API surfaces."""
    normalized = dict(user)
    username = (
        normalized.get("username")
        or normalized.get("id")
        or normalized.get("email")
    )
    roles = list(normalized.get("roles") or [])
    permissions = list(normalized.get("permissions") or roles)
    raw_is_admin = normalized.get("is_admin")
    is_admin = bool("admin" in roles if raw_is_admin is None else raw_is_admin)

    if is_admin and "admin" not in permissions:
        permissions.append("admin")

    normalized["username"] = username
    normalized["id"] = normalized.get("id") or username
    normalized["roles"] = roles
    normalized["permissions"] = permissions
    normalized["is_admin"] = is_admin
    normalized.setdefault("is_active", True)

    return normalized


def _check_permission(user_info: Dict[str, Any], required_role: str) -> bool:
    """Check whether a normalized user payload grants the requested role."""
    user_roles = user_info.get("roles", [])
    if "admin" in user_roles:
        return True
    return required_role in user_roles


class TokenManager:
    """JWT token management."""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.secret_key = settings.secret_key
        self.algorithm = settings.jwt_algorithm
        self.expire_hours = settings.jwt_expire_hours
    
    def create_access_token(self, data: Dict[str, Any]) -> str:
        """Create JWT access token."""
        to_encode = data.copy()
        now = datetime.now(UTC)
        expire = now + timedelta(hours=self.expire_hours)
        to_encode.update({"exp": expire, "iat": now})
        
        encoded_jwt = jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)
        return encoded_jwt
    
    def verify_token(self, token: str) -> Dict[str, Any]:
        """Verify and decode JWT token."""
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            return payload
        except JWTError as e:
            logger.warning(f"JWT verification failed: {e}")
            raise AuthenticationError("Invalid token")
    
    def decode_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Decode token without verification (for debugging)."""
        try:
            return jwt.decode(token, options={"verify_signature": False})
        except JWTError:
            return None


class AuthenticationMiddleware(BaseHTTPMiddleware):
    """Authentication middleware for FastAPI."""
    
    def __init__(self, app: ASGIApp, settings: Settings):
        super().__init__(app)
        self.settings = settings
        self.token_manager = TokenManager(settings)
        self.enabled = settings.enable_authentication
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request through authentication middleware."""
        start_time = time.time()
        
        try:
            # Skip authentication for certain paths
            if self._should_skip_auth(request):
                response = await call_next(request)
                return response
            
            # Skip if authentication is disabled
            if not self.enabled:
                response = await call_next(request)
                return response
            
            # Extract and verify token
            user_info = await self._authenticate_request(request)
            
            # Set user context
            if user_info:
                request.state.user = user_info
                set_request_context(user_id=user_info.get("username"))
            
            # Process request
            response = await call_next(request)
            
            # Add authentication headers
            self._add_auth_headers(response, user_info)
            
            return response
            
        except AuthenticationError as e:
            logger.warning(f"Authentication failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(e),
                headers={"WWW-Authenticate": "Bearer"},
            )
        except AuthorizationError as e:
            logger.warning(f"Authorization failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=str(e),
            )
        except Exception as e:
            logger.error(f"Authentication middleware error: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Authentication service error",
            )
        finally:
            # Log request processing time
            processing_time = time.time() - start_time
            logger.debug(f"Auth middleware processing time: {processing_time:.3f}s")
    
    def _should_skip_auth(self, request: Request) -> bool:
        """Check if authentication should be skipped for this request."""
        return is_public_http_path(request.url.path)
    
    async def _authenticate_request(self, request: Request) -> Optional[Dict[str, Any]]:
        """Authenticate the request and return user info."""
        # Try to get token from Authorization header
        authorization = request.headers.get("Authorization")
        if not authorization:
            # For WebSocket connections, try to get token from query parameters
            if request.url.path.startswith("/ws"):
                token = request.query_params.get("token")
                if token:
                    authorization = f"Bearer {token}"
        
        if not authorization:
            if self._requires_auth(request):
                raise AuthenticationError("Missing authorization header")
            return None
        
        # Extract token
        try:
            scheme, token = authorization.split()
            if scheme.lower() != "bearer":
                raise AuthenticationError("Invalid authentication scheme")
        except ValueError:
            raise AuthenticationError("Invalid authorization header format")
        
        # Verify token
        try:
            payload = self.token_manager.verify_token(token)
            username = payload.get("sub")
            if not username:
                raise AuthenticationError("Invalid token payload")

            return _normalize_authenticated_user(
                {
                    "id": payload.get("id"),
                    "username": username,
                    "email": payload.get("email"),
                    "roles": payload.get("roles", []),
                    "permissions": payload.get("permissions"),
                    "is_admin": payload.get("is_admin"),
                    "is_active": payload.get("is_active", True),
                    "zones": payload.get("zones", []),
                    "routers": payload.get("routers", []),
                }
            )
            
        except AuthenticationError:
            raise
        except Exception as e:
            logger.error(f"Token verification error: {e}")
            raise AuthenticationError("Token verification failed")
    
    def _requires_auth(self, request: Request) -> bool:
        """Check if the request requires authentication."""
        # All API endpoints require authentication by default
        path = request.url.path
        return path.startswith("/api/") or path.startswith("/ws/")
    
    def _add_auth_headers(self, response: Response, user_info: Optional[Dict[str, Any]]):
        """Add authentication-related headers to response."""
        if user_info:
            response.headers["X-User"] = user_info["username"]
            response.headers["X-User-Roles"] = ",".join(user_info["roles"])
    
    async def login(self, username: str, password: str) -> Dict[str, Any]:
        """Authenticate user and return token."""
        raise AuthenticationError(
            "Interactive login is not implemented in the current runtime"
        )
    
    async def register(self, username: str, email: str, password: str) -> Dict[str, Any]:
        """Register a new user."""
        raise AuthenticationError(
            "Interactive registration is not implemented in the current runtime"
        )
    
    async def refresh_token(self, token: str) -> Dict[str, Any]:
        """Refresh an access token."""
        try:
            payload = self.token_manager.verify_token(token)
            username = payload.get("sub")
            if not username:
                raise AuthenticationError("Invalid token payload")
            
            # Create new token
            token_data = {
                "sub": username,
                "email": payload.get("email"),
                "roles": payload.get("roles", []),
                "permissions": payload.get("permissions"),
                "is_admin": payload.get("is_admin"),
                "is_active": payload.get("is_active", True),
                "zones": payload.get("zones", []),
                "routers": payload.get("routers", []),
            }
            
            new_token = self.token_manager.create_access_token(token_data)
            
            return {
                "access_token": new_token,
                "token_type": "bearer",
                "expires_in": self.settings.jwt_expire_hours * 3600,
            }
            
        except Exception:
            raise AuthenticationError("Token refresh failed")
    
    def check_permission(self, user_info: Dict[str, Any], required_role: str) -> bool:
        """Check if user has required role/permission."""
        return _check_permission(user_info, required_role)
    
    def require_role(self, required_role: str):
        """Decorator to require specific role."""
        def decorator(func):
            import functools
            
            @functools.wraps(func)
            async def wrapper(request: Request, *args, **kwargs):
                user_info = getattr(request.state, "user", None)
                if not user_info:
                    raise AuthorizationError("Authentication required")
                
                if not self.check_permission(user_info, required_role):
                    raise AuthorizationError(f"Role '{required_role}' required")
                
                return await func(request, *args, **kwargs)
            
            return wrapper
        return decorator


def get_current_user(request: Request) -> Optional[Dict[str, Any]]:
    """Get current authenticated user from request."""
    user = getattr(request.state, "user", None)
    if not user:
        return None
    return _normalize_authenticated_user(user)


def require_authentication(request: Request) -> Dict[str, Any]:
    """Require authentication and return user info."""
    user = get_current_user(request)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_role(role: str):
    """Dependency to require specific role."""
    def dependency(request: Request) -> Dict[str, Any]:
        user = require_authentication(request)

        if not _check_permission(user, role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{role}' required",
            )
        
        return user
    
    return dependency
