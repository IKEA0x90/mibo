"""
User Manager API
Allows editing of user information defined in UserWrapper.
Cannot edit telegram-defined fields (username, user_id).
All operations go through ref.py.
"""

from typing import List, Dict, Optional
from fastapi import APIRouter, HTTPException, status, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core import wrapper
from events import system_events

class UserInfo(BaseModel):
    user_id: str
    username: str
    preferred_name: str
    image_generation_limit: int
    deep_research_limit: int
    utc_offset: int
    admin_chats: List[str]

class UpdateUserRequest(BaseModel):
    user_id: str
    preferred_name: Optional[str] = None
    image_generation_limit: Optional[int] = None
    deep_research_limit: Optional[int] = None
    utc_offset: Optional[int] = None
    admin_chats: Optional[List[str]] = None

def create_user_manager_router(webapp) -> APIRouter:
    """Create user manager router with access to the webapp instance."""
    router = APIRouter()
    
    @router.get("/users", response_model=List[UserInfo])
    async def get_all_users(user: dict = Depends(webapp.get_current_user)):
        """
        Get all users from ref.
        Returns list of user information.
        """
        try:
            users = []
            for user_id, user_obj in webapp.ref.users.items():
                users.append(UserInfo(
                    user_id=user_obj.id,
                    username=user_obj.username,
                    preferred_name=user_obj.preferred_name,
                    image_generation_limit=user_obj.image_generation_limit,
                    deep_research_limit=user_obj.deep_research_limit,
                    utc_offset=user_obj.utc_offset,
                    admin_chats=user_obj.admin_chats
                ))
            
            # Sort by username
            users.sort(key=lambda x: x.username)
            return users
            
        except Exception as e:
            webapp.bus.emit_sync(system_events.ErrorEvent(
                error="Failed to retrieve users",
                e=e,
                tb=None
            ))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve users"
            )
    
    @router.get("/user/{user_id}", response_model=UserInfo)
    async def get_user(user_id: str, user: dict = Depends(webapp.get_current_user)):
        """
        Get details of a specific user.
        """
        try:
            user_obj = await webapp.ref.get_user(user_id)
            
            return UserInfo(
                user_id=user_obj.id,
                username=user_obj.username,
                preferred_name=user_obj.preferred_name,
                image_generation_limit=user_obj.image_generation_limit,
                deep_research_limit=user_obj.deep_research_limit,
                utc_offset=user_obj.utc_offset,
                admin_chats=user_obj.admin_chats
            )
            
        except Exception as e:
            webapp.bus.emit_sync(system_events.ErrorEvent(
                error=f"Failed to retrieve user {user_id}",
                e=e,
                tb=None
            ))
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User {user_id} not found"
            )
    
    @router.put("/user")
    async def update_user(request: UpdateUserRequest, user: dict = Depends(webapp.get_current_user)):
        """
        Update user information.
        Uses ref.update_user to save changes.
        Cannot update username or user_id (telegram-defined fields).
        """
        try:
            user_obj = await webapp.ref.get_user(request.user_id)
            
            # Update fields if provided
            if request.preferred_name is not None:
                user_obj.preferred_name = request.preferred_name
            if request.image_generation_limit is not None:
                user_obj.image_generation_limit = request.image_generation_limit
            if request.deep_research_limit is not None:
                user_obj.deep_research_limit = request.deep_research_limit
            if request.utc_offset is not None:
                user_obj.utc_offset = request.utc_offset
            if request.admin_chats is not None:
                user_obj.admin_chats = request.admin_chats
            
            # Save through ref
            await webapp.ref.update_user(user_obj)
            
            return {
                "success": True,
                "message": f"User {request.user_id} updated successfully",
                "user": UserInfo(
                    user_id=user_obj.id,
                    username=user_obj.username,
                    preferred_name=user_obj.preferred_name,
                    image_generation_limit=user_obj.image_generation_limit,
                    deep_research_limit=user_obj.deep_research_limit,
                    utc_offset=user_obj.utc_offset,
                    admin_chats=user_obj.admin_chats
                )
            }
            
        except HTTPException:
            raise
        except Exception as e:
            webapp.bus.emit_sync(system_events.ErrorEvent(
                error=f"Failed to update user {request.user_id}",
                e=e,
                tb=None
            ))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update user"
            )
    
    @router.get("/chats")
    async def get_available_chats(user: dict = Depends(webapp.get_current_user)):
        """
        Get all available chats for admin_chats configuration.
        """
        try:
            chats = []
            for chat_id, chat in webapp.ref.chats.items():
                chats.append({
                    "id": chat_id,
                    "name": chat.chat_name or f"Chat {chat_id}"
                })
            
            # Sort by name
            chats.sort(key=lambda x: x["name"])
            return chats
            
        except Exception as e:
            webapp.bus.emit_sync(system_events.ErrorEvent(
                error="Failed to retrieve chats",
                e=e,
                tb=None
            ))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve chats"
            )
    
    return router