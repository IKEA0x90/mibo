"""
All the API needed for all auth logic.
Handles login, logout, and token verification.
"""

import hashlib
import secrets
from typing import Optional
from fastapi import APIRouter, HTTPException, status, Form, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core import wrapper
from events import system_events
from web import web

class LoginRequest(BaseModel):
    username: str
    password: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user_id: str
    username: str

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a password against its hash.
    For now using simple SHA256 hash comparison.
    In production, use bcrypt or argon2.
    """
    try:
        # Create SHA256 hash of the plain password
        plain_hash = hashlib.sha256(plain_password.encode('utf-8')).hexdigest()
        return secrets.compare_digest(plain_hash, hashed_password)
    except Exception:
        return False

def create_auth_router(webapp: web.WebApp) -> APIRouter:
    """Create authentication router with access to the webapp instance."""
    router = APIRouter()
    
    @router.post("/login", response_model=LoginResponse)
    async def login(request: LoginRequest):
        """
        Authenticate user and return JWT token.
        Users must have a password hash to be considered registered.
        """
        try:
            # Find user by username in ref.users
            user_found = None
            user: wrapper.UserWrapper
            for user_id, user in webapp.ref.users.items():
                if user.username == request.username:
                    user_found = user
                    break
            
            if not user_found:
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"detail": "Invalid username or password"}
                )
            
            # Check if user is registered (has password)
            if not user_found.password:
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"detail": "User not registered"}
                )
            
            # Verify password
            if not verify_password(request.password, user_found.password):
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"detail": "Invalid username or password"}
                )
            
            # Create JWT token
            token_data = {
                "user_id": user_found.id,
                "username": user_found.username
            }
            
            access_token = webapp.create_access_token(token_data)
            
            return LoginResponse(
                access_token=access_token,
                expires_in=webapp.JWT_EXPIRE_MINUTES * 60,  # Convert to seconds
                user_id=user_found.id,
                username=user_found.username
            )
            
        except Exception as e:
            webapp.bus.emit_sync(system_events.ErrorEvent(
                error="Login failed due to internal error",
                e=e,
                tb=None
            ))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"{e}"
            )
    
    @router.post("/logout")
    async def logout(user: dict = Depends(webapp.get_current_user)):
        """
        Logout current user.
        Since we're using stateless JWT, this is mainly for frontend cleanup.
        """
        return {"message": "Successfully logged out"}
    
    @router.get("/me")
    async def get_current_user_info(user: dict = Depends(webapp.get_current_user)):
        """Get current authenticated user information."""
        return {
            "user_id": user["user_id"],
            "username": user["username"],
            "admin_chats": user["admin_chats"]
        }
    
    @router.get("/verify")
    async def verify_token(user: dict = Depends(webapp.get_current_user)):
        """Verify if the provided token is valid."""
        return {"valid": True, "user": user}
    
    return router