"""
All the API needed for all auth logic.
Handles login, logout, and token verification.
"""

import hashlib
import secrets
from typing import Optional
from fastapi import APIRouter, HTTPException, status, Form, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core import wrapper
from events import system_events

class LoginRequest(BaseModel):
    username: str
    token: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user_id: str
    username: str

def create_auth_router(webapp) -> APIRouter:
    """Create authentication router with access to the webapp instance."""
    router = APIRouter()
    
    @router.post("/login", response_model=LoginResponse)
    async def login(request: LoginRequest, http_request: Request):
        """
        Authenticate user and return JWT token.
        """
        client_ip = http_request.client.host if http_request.client else "unknown"
        try:
            # Find user by username in ref.users
            user_found = None
            user: wrapper.UserWrapper
            
            # Enhanced logging: Log login attempt
            print(f"LOGIN ATTEMPT: Username='{request.username}', IP={client_ip}")

            for user_id, user in webapp.ref.users.items():
                if user.username == request.username:
                    user_found = user
                    break
            
            if not user_found:
                print(f"LOGIN FAILED: Username '{request.username}' not found in system (IP: {client_ip})")
                print(f"  Available users: {list(webapp.ref.users.keys())} with usernames: {[u.username for u in webapp.ref.users.values()]}")
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"detail": "Invalid username or token"}
                )
            
            # Check if user is registered (has token)
            if not user_found.token:
                print(f"LOGIN FAILED: User '{request.username}' (ID: {user_found.id}) has no token set - not registered (IP: {client_ip})")
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"detail": "User not registered"}
                )

            # Verify token
            stored_token = user_found.token
            if not stored_token:
                print(f"LOGIN FAILED: User '{request.username}' (ID: {user_found.id}) token already consumed or cleared (IP: {client_ip})")
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"detail": "Token already used or expired. Please request a new token."}
                )
                
            if stored_token != request.token:
                print(f"LOGIN FAILED: Invalid token for user '{request.username}' (ID: {user_found.id}) - stored token length: {len(stored_token)}, provided token length: {len(request.token)} (IP: {client_ip})")
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"detail": "Invalid username or token"}
                )

            # Clear the one-time token immediately after successful verification to prevent reuse
            # This is atomic and prevents race conditions from multiple login attempts
            print(f"LOGIN SUCCESS: Clearing one-time token for user '{request.username}' (ID: {user_found.id}) (IP: {client_ip})")
            webapp.ref.users[user_found.id].token = ''

            # Create JWT token
            token_data = {
                "user_id": user_found.id,
                "username": user_found.username
            }
            
            access_token = webapp.create_access_token(token_data)
            
            print(f"LOGIN SUCCESS: JWT token created for user '{request.username}' (ID: {user_found.id}), expires in {webapp.JWT_EXPIRE_MINUTES} minutes (IP: {client_ip})")
            
            return LoginResponse(
                access_token=access_token,
                expires_in=webapp.JWT_EXPIRE_MINUTES * 60,  # Convert to seconds
                user_id=user_found.id,
                username=user_found.username
            )
            
        except Exception as e:
            print(f"LOGIN ERROR: Internal server error during login for username '{request.username}' (IP: {client_ip}): {e}")
            webapp.bus.emit_sync(system_events.ErrorEvent(
                error=f"Login failed due to internal error for user '{request.username}'",
                e=e,
                tb=None
            ))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Internal server error during login"
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