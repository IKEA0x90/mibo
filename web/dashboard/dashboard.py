'''
Code preserved for reference. Delete old code after refactoring.
See new requirements in dashboard.html

from typing import List, Dict
from fastapi import APIRouter, HTTPException, status, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core import wrapper
from events import system_events

class ChatInfo(BaseModel):
    chat_id: str
    chat_name: str
    chance: int
    assistant_id: str
    ai_model_id: str

class ClearChatRequest(BaseModel):
    chat_id: str

class ClearChatResponse(BaseModel):
    success: bool
    message: str
    chat_id: str

def create_dashboard_router(webapp) -> APIRouter:
    """Create dashboard router with access to the webapp instance."""
    router = APIRouter()
    
    @router.get("/chats", response_model=List[ChatInfo])
    async def get_all_chats(user: dict = Depends(webapp.get_current_user)):
        """
        Get all available chats from the ref.chats field.
        Returns list of chat information for the dropdown.
        """
        try:
            chats = []
            for chat_id, chat in webapp.ref.chats.items():
                chats.append(ChatInfo(
                    chat_id=chat.id,
                    chat_name=chat.chat_name or f"Chat {chat.id}",
                    chance=chat.chance,
                    assistant_id=chat.assistant_id,
                    ai_model_id=chat.ai_model_id
                ))
            
            # Sort by chat name for better UX
            chats.sort(key=lambda x: x.chat_name)
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
    
    @router.post("/clear", response_model=ClearChatResponse)
    async def clear_chat(request: ClearChatRequest, user: dict = Depends(webapp.get_current_user)):
        """
        Clear a chat window using mibo.clear functionality.
        Uses the ref.clear method as specified.
        """
        try:
            chat_id = request.chat_id
            
            # Validate that the chat exists
            if chat_id not in webapp.ref.chats:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Chat {chat_id} not found"
                )
            
            # Clear the chat using ref.clear
            cleared_window = await webapp.ref.clear(chat_id)
            
            return ClearChatResponse(
                success=True,
                message=f"Chat {chat_id} cleared successfully",
                chat_id=chat_id
            )
            
        except HTTPException:
            raise
        except Exception as e:
            webapp.bus.emit_sync(system_events.ErrorEvent(
                error=f"Failed to clear chat {request.chat_id}",
                e=e,
                tb=None
            ))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to clear chat"
            )
    
    @router.get("/user/info")
    async def get_user_info(user: dict = Depends(webapp.get_current_user)):
        """Get current user information for the dashboard."""
        try:
            user_wrapper = await webapp.ref.get_user(user["user_id"])
            
            return {
                "user_id": user_wrapper.id,
                "username": user_wrapper.username,
                "preferred_name": user_wrapper.preferred_name,
                "admin_chats": user_wrapper.admin_chats,
                "image_generation_limit": user_wrapper.image_generation_limit,
                "deep_research_limit": user_wrapper.deep_research_limit,
                "utc_offset": user_wrapper.utc_offset
            }
        except Exception as e:
            webapp.bus.emit_sync(system_events.ErrorEvent(
                error="Failed to get user info",
                e=e,
                tb=None
            ))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to get user information"
            )
    
    @router.get("/stats")
    async def get_dashboard_stats(user: dict = Depends(webapp.get_current_user)):
        """Get basic statistics for the dashboard."""
        try:
            total_chats = len(webapp.ref.chats)
            total_users = len(webapp.ref.users)
            
            # Count active chats (recently used)
            import time
            current_time = time.time()
            active_chats = sum(1 for chat in webapp.ref.chats.values() 
                             if (current_time - chat.last_active) < 3600)  # Active in last hour
            
            return {
                "total_chats": total_chats,
                "active_chats": active_chats,
                "total_users": total_users
            }
        except Exception as e:
            webapp.bus.emit_sync(system_events.ErrorEvent(
                error="Failed to get dashboard stats",
                e=e,
                tb=None
            ))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to get statistics"
            )
    
    return router 

'''