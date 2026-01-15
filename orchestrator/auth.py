# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

"""
Authentication utilities for the UI dashboard.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

import config


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
    
    def __init__(self):
        self._secret = config.DashboardAuthConfig.JWT_SECRET
        self._algorithm = config.DashboardAuthConfig.JWT_ALGORITHM
        self._expire_hours = config.DashboardAuthConfig.JWT_EXPIRE_HOURS

    def authenticate(self, username: str, password: str) -> bool:
        """Validate username and password against configured credentials."""
        return (
            username == config.DashboardAuthConfig.USERNAME and
            password == config.DashboardAuthConfig.PASSWORD
        )

    def create_token(self, username: str) -> TokenResponse:
        """Create a JWT token for an authenticated user."""
        expires_at = datetime.now(timezone.utc) + timedelta(hours=self._expire_hours)
        payload = {
            "sub": username,
            "exp": expires_at,
            "iat": datetime.now(timezone.utc),
        }
        token = jwt.encode(payload, self._secret, algorithm=self._algorithm)
        return TokenResponse(
            access_token=token,
            expires_at=expires_at.isoformat(),
        )

    def verify_token(self, token: str) -> Optional[str]:
        """
        Verify a JWT token and return the username if valid.
        
        Returns:
            The username if the token is valid, None otherwise.
        """
        try:
            payload = jwt.decode(token, self._secret, algorithms=[self._algorithm])
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

    async def __call__(self, request: Request) -> Optional[str]:
        """Validate the bearer token and return the username."""
        credentials: Optional[HTTPAuthorizationCredentials] = await super().__call__(request)
        
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
