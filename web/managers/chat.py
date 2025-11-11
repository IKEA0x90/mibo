"""
Chat Manager API
Allows management of chat configuration and window messages.
All operations go through ref.py.
"""

from typing import List, Dict, Optional
from fastapi import APIRouter, HTTPException, status, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core import wrapper, window
from events import system_events, ref_events

class ChatInfo(BaseModel):
    chat_id: str
    chat_name: str
    chance: int
    assistant_id: str
    ai_model_id: str

class UpdateChatRequest(BaseModel):
    chat_id: str
    chat_name: Optional[str] = None
    chance: Optional[int] = None
    assistant_id: Optional[str] = None
    ai_model_id: Optional[str] = None

class ChatWindowMessage(BaseModel):
    id: str
    type: str
    role: str
    user: str
    datetime: str
    content: str
    reply_id: Optional[str] = None

class ClearWindowRequest(BaseModel):
    chat_id: str

class RemoveMessagesRequest(BaseModel):
    chat_id: str
    message_ids: List[str]

def create_chat_manager_router(webapp) -> APIRouter:
    """Create chat manager router with access to the webapp instance."""
    router = APIRouter()
    
    @router.get("/chats", response_model=List[ChatInfo])
    async def get_all_chats(user: dict = Depends(webapp.get_current_user)):
        """
        Get all available chats.
        Returns list of chat information.
        """
        try:
            chats = []
            for chat_id, chat in webapp.ref.chats.items():
                chats.append(ChatInfo(
                    chat_id=chat.id,
                    chat_name=getattr(chat, 'chat_name', f"Chat {chat.id}"),
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
    
    @router.get("/chat/{chat_id}", response_model=ChatInfo)
    async def get_chat(chat_id: str, user: dict = Depends(webapp.get_current_user)):
        """
        Get details of a specific chat.
        """
        try:
            chat = await webapp.ref.get_chat(chat_id)
            
            return ChatInfo(
                chat_id=chat.id,
                chat_name=chat.chat_name or f"Chat {chat.id}",
                chance=chat.chance,
                assistant_id=chat.assistant_id,
                ai_model_id=chat.ai_model_id
            )
            
        except Exception as e:
            webapp.bus.emit_sync(system_events.ErrorEvent(
                error=f"Failed to retrieve chat {chat_id}",
                e=e,
                tb=None
            ))
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Chat {chat_id} not found"
            )
    
    @router.put("/chat")
    async def update_chat(request: UpdateChatRequest, user: dict = Depends(webapp.get_current_user)):
        """
        Update chat configuration.
        Uses ref.py to update chat settings.
        """
        try:
            chat = await webapp.ref.get_chat(request.chat_id)
            
            # Update fields if provided
            if request.chat_name is not None:
                chat.chat_name = request.chat_name
            if request.chance is not None:
                chat.chance = request.chance
            if request.assistant_id is not None:
                chat.assistant_id = request.assistant_id
            if request.ai_model_id is not None:
                chat.ai_model_id = request.ai_model_id
            
            # Save to database through ref
            webapp.ref.chats[chat.id] = chat
            # Emit event to save to database
            await webapp.bus.emit(ref_events.NewChat(chat, update=True))
            
            return {
                "success": True,
                "message": f"Chat {request.chat_id} updated successfully",
                "chat": ChatInfo(
                    chat_id=chat.id,
                    chat_name=chat.chat_name,
                    chance=chat.chance,
                    assistant_id=chat.assistant_id,
                    ai_model_id=chat.ai_model_id
                )
            }
            
        except HTTPException:
            raise
        except Exception as e:
            webapp.bus.emit_sync(system_events.ErrorEvent(
                error=f"Failed to update chat {request.chat_id}",
                e=e,
                tb=None
            ))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update chat"
            )
    
    @router.get("/window/{chat_id}", response_model=List[ChatWindowMessage])
    async def get_chat_window(chat_id: str, user: dict = Depends(webapp.get_current_user)):
        """
        Get all messages in a chat's window.
        Returns messages in order with content formatted.
        """
        try:
            # Add some basic validation for chat_id
            if not chat_id or chat_id.strip() == "":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Chat ID cannot be empty"
                )
            
            if chat_id == "[object PointerEvent]":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid chat_id: received JavaScript event object instead of chat ID"
                )
            
            wdw = await webapp.ref.get_window(chat_id)
            
            messages = []
            for msg in wdw.messages:
                content = ""
                if isinstance(msg, wrapper.MessageWrapper):
                    content = msg.message
                elif isinstance(msg, wrapper.ImageWrapper):
                    content = "|IMAGE|"
                else:
                    content = str(msg)
                
                messages.append(ChatWindowMessage(
                    id=msg.id,
                    type=msg.type,
                    role=msg.role,
                    user=msg.user,
                    datetime=msg.datetime.isoformat() if hasattr(msg, 'datetime') else "",
                    content=content,
                    reply_id=msg.reply_id if hasattr(msg, 'reply_id') else None
                ))
            
            # Sort messages by ID in descending order (highest to lowest)
            messages.sort(key=lambda x: int(x.id), reverse=True)
            
            return messages
            
        except Exception as e:
            webapp.bus.emit_sync(system_events.ErrorEvent(
                error=f"Failed to retrieve window for chat {chat_id}",
                e=e,
                tb=None
            ))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve chat window"
            )

    @router.post("/window/clear")
    async def clear_window(request: ClearWindowRequest, user: dict = Depends(webapp.get_current_user)):
        """
        Clear all messages from a chat window.
        Uses ref.clear method.
        """
        try:
            # Clear the chat window using ref.clear
            cleared_window = await webapp.ref.clear(request.chat_id)
            
            return {
                "success": True,
                "message": f"Window for chat {request.chat_id} cleared successfully",
                "chat_id": request.chat_id
            }
            
        except Exception as e:
            webapp.bus.emit_sync(system_events.ErrorEvent(
                error=f"Failed to clear window for chat {request.chat_id}",
                e=e,
                tb=None
            ))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to clear chat window"
            )
    
    @router.post("/window/remove")
    async def remove_messages(request: RemoveMessagesRequest, user: dict = Depends(webapp.get_current_user)):
        """
        Remove specific messages from a chat window.
        Does not delete from database, only from window.
        """
        try:
            wdw = await webapp.ref.get_window(request.chat_id)
            
            # Remove messages with matching IDs
            removed_count = 0
            messages_to_keep = []
            
            for msg in wdw.messages:
                if msg.id not in request.message_ids:
                    messages_to_keep.append(msg)
                else:
                    removed_count += 1
            
            # Clear window and re-add kept messages
            async with wdw._lock:
                wdw.messages.clear()
                wdw.tokens = 0
                
                for msg in messages_to_keep:
                    await wdw._insert_live_message(msg)
            
            return {
                "success": True,
                "message": f"Removed {removed_count} message(s) from window",
                "chat_id": request.chat_id,
                "removed_count": removed_count
            }
            
        except Exception as e:
            webapp.bus.emit_sync(system_events.ErrorEvent(
                error=f"Failed to remove messages from chat {request.chat_id}",
                e=e,
                tb=None
            ))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to remove messages"
            )
    
    @router.get("/assistants")
    async def get_available_assistants(user: dict = Depends(webapp.get_current_user)):
        """
        Get all available assistants for chat configuration.
        """
        try:
            assistants = []
            for assistant_id, assistant in webapp.ref.assistants.items():
                assistants.append({
                    "id": assistant_id,
                    "name": assistant.id
                })
            
            return assistants
            
        except Exception as e:
            webapp.bus.emit_sync(system_events.ErrorEvent(
                error="Failed to retrieve assistants",
                e=e,
                tb=None
            ))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve assistants"
            )
    
    @router.get("/models")
    async def get_available_models(user: dict = Depends(webapp.get_current_user)):
        """
        Get all available AI models for chat configuration.
        """
        try:
            models = []
            for model_id, model in webapp.ref.models.items():
                models.append({
                    "id": model_id,
                    "name": model.id
                })
            
            return models
            
        except Exception as e:
            webapp.bus.emit_sync(system_events.ErrorEvent(
                error="Failed to retrieve models",
                e=e,
                tb=None
            ))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve models"
            )
    
    return router