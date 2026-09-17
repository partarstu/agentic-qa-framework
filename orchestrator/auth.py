# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""
Authentication utilities for the UI dashboard.
"""

import hmac
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from fastapi import HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

import config
from common import utils

logger = utils.get_logger("auth")


class LoginRequest(BaseModel):
    """Request model for login endpoint."""

    username: str
    password: str


class TokenResponse(BaseModel):
    """Response model for successful login."""

    access_token: str
    token_type: str = "bearer"
    expires_at: str


class AuthService:
    """Service for handling dashboard authentication."""

    @staticmethod
    def _is_configured() -> bool:
        """Whether all required dashboard auth settings are present.

        Read dynamically (not cached) so a misconfigured deployment fails closed and
        tests can override the settings on config at runtime.
        """
        return bool(
            config.DashboardAuthConfig.USERNAME
            and config.DashboardAuthConfig.PASSWORD_HASH
            and config.DashboardAuthConfig.JWT_SECRET
        )

    @staticmethod
    def validate_configuration() -> None:
        """Raise when dashboard credentials cannot securely authenticate a login."""
        if not AuthService._is_configured():
            raise RuntimeError("DASHBOARD_USERNAME, DASHBOARD_PASSWORD_HASH and DASHBOARD_JWT_SECRET are required.")
        try:
            bcrypt.checkpw(b"", config.DashboardAuthConfig.PASSWORD_HASH.encode("utf-8"))
        except ValueError as exc:
            raise RuntimeError("DASHBOARD_PASSWORD_HASH is not a valid bcrypt hash.") from exc

    def authenticate(self, username: str, password: str) -> bool:
        """Validate username and password against configured credentials.

        Fails closed: if credentials or the JWT secret are not configured, no login is
        accepted (an empty configured value must never match an empty submitted value).
        The comparison is constant-time to avoid leaking credentials via timing.
        """
        if not self._is_configured():
            logger.error("Dashboard authentication is not configured; rejecting login attempt.")
            return False
        username_ok = hmac.compare_digest(username, config.DashboardAuthConfig.USERNAME)
        if len(password.encode("utf-8")) > 72:
            return False
        password_ok = bcrypt.checkpw(password.encode("utf-8"), config.DashboardAuthConfig.PASSWORD_HASH.encode("utf-8"))
        return username_ok and password_ok

    def create_token(self, username: str) -> TokenResponse:
        """Create a JWT token for an authenticated user."""
        if not self._is_configured():
            raise HTTPException(status_code=503, detail="Authentication is not configured.")
        expires_at = datetime.now(UTC) + timedelta(hours=config.DashboardAuthConfig.JWT_EXPIRE_HOURS)
        payload = {
            "sub": username,
            "exp": expires_at,
            "iat": datetime.now(UTC),
        }
        token = jwt.encode(payload, config.DashboardAuthConfig.JWT_SECRET, algorithm=config.DashboardAuthConfig.JWT_ALGORITHM)
        return TokenResponse(
            access_token=token,
            expires_at=expires_at.isoformat(),
        )

    def verify_token(self, token: str) -> str | None:
        """
        Verify a JWT token and return the username if valid.

        Returns:
            The username if the token is valid, None otherwise.
        """
        # Fail closed: without a configured secret, no token can be trusted.
        if not config.DashboardAuthConfig.JWT_SECRET:
            logger.error("DASHBOARD_JWT_SECRET is not configured; rejecting token verification.")
            return None
        try:
            payload = jwt.decode(
                token,
                config.DashboardAuthConfig.JWT_SECRET,
                algorithms=[config.DashboardAuthConfig.JWT_ALGORITHM],
            )
            return payload.get("sub")
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None


class DashboardAuthBearer(HTTPBearer):
    """Custom HTTP Bearer authentication for dashboard routes."""

    def __init__(self, auth_service: AuthService, auto_error: bool = True):
        super().__init__(auto_error=auto_error)
        self._auth_service = auth_service

    async def __call__(self, request: Request) -> str | None:
        """Validate the bearer token and return the username."""
        credentials: HTTPAuthorizationCredentials | None = await super().__call__(request)

        if credentials is None:
            if self.auto_error:
                raise HTTPException(status_code=401, detail="Not authenticated")
            return None

        username = self._auth_service.verify_token(credentials.credentials)
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid or expired token")

        return username


# Singleton instances
auth_service = AuthService()
dashboard_auth = DashboardAuthBearer(auth_service)


class LoginRateLimiter:
    """Bound login attempts per client in a bounded sliding time window."""

    def __init__(self, max_addresses: int = 10_000) -> None:
        self._attempts: dict[str, deque[float]] = defaultdict(deque)
        self._max_addresses = max_addresses

    def check(self, client_ip: str, now: float | None = None) -> int | None:
        """Record an attempt and return retry seconds when the client is rate limited."""
        timestamp = time.monotonic() if now is None else now
        window = config.DashboardAuthConfig.LOGIN_RATE_LIMIT_WINDOW_SECONDS
        attempts = self._attempts[client_ip]
        while attempts and attempts[0] <= timestamp - window:
            attempts.popleft()
        if len(attempts) >= config.DashboardAuthConfig.LOGIN_RATE_LIMIT_ATTEMPTS:
            return max(1, int(window - (timestamp - attempts[0])))
        attempts.append(timestamp)
        if len(self._attempts) > self._max_addresses:
            self._attempts.pop(next(iter(self._attempts)))
        return None


def client_ip(request: Request) -> str:
    """Return the client address using only configured trusted proxy hops."""
    hops = config.DashboardAuthConfig.LOGIN_RATE_LIMIT_TRUSTED_PROXY_HOPS
    forwarded = [item.strip() for item in request.headers.get("X-Forwarded-For", "").split(",") if item.strip()]
    if hops and len(forwarded) >= hops:
        return forwarded[-hops]
    return request.client.host if request.client else "unknown"


login_rate_limiter = LoginRateLimiter()
