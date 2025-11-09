"""
Reference Manager API
Allows management of references (assistants, models, prompts).
All operations go through ref.py.
"""

from typing import List, Dict, Optional
from fastapi import APIRouter, HTTPException, status, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import json

from core import ref
from events import system_events

class ReferenceInfo(BaseModel):
    id: str
    type: str

class UpdateReferenceRequest(BaseModel):
    ref_type: str
    ref_id: str
    data: Dict

def create_reference_manager_router(webapp) -> APIRouter:
    """Create reference manager router with access to the webapp instance."""
    router = APIRouter()
    
    @router.get("/types")
    async def get_reference_types(user: dict = Depends(webapp.get_current_user)):
        """
        Get available reference types.
        """
        return {
            "types": ["assistants", "models", "prompts"]
        }
    
    @router.get("/list/{ref_type}")
    async def get_references(ref_type: str, user: dict = Depends(webapp.get_current_user)):
        """
        Get all references of a specific type.
        """
        try:
            references = []
            
            if ref_type == "assistants":
                for ref_id, reference in webapp.ref.assistants.items():
                    references.append(ReferenceInfo(
                        id=ref_id,
                        type="assistant"
                    ))
            elif ref_type == "models":
                for ref_id, reference in webapp.ref.models.items():
                    references.append(ReferenceInfo(
                        id=ref_id,
                        type="model"
                    ))
            elif ref_type == "prompts":
                for ref_id, reference in webapp.ref.prompts.items():
                    references.append(ReferenceInfo(
                        id=ref_id,
                        type="prompt"
                    ))
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid reference type: {ref_type}"
                )
            
            return references
            
        except HTTPException:
            raise
        except Exception as e:
            webapp.bus.emit_sync(system_events.ErrorEvent(
                error=f"Failed to retrieve {ref_type}",
                e=e,
                tb=None
            ))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to retrieve {ref_type}"
            )
    
    @router.get("/get/{ref_type}/{ref_id}")
    async def get_reference(ref_type: str, ref_id: str, user: dict = Depends(webapp.get_current_user)):
        """
        Get a specific reference as JSON.
        """
        try:
            reference_obj = None
            
            if ref_type == "assistants":
                reference_obj = webapp.ref.assistants.get(ref_id)
            elif ref_type == "models":
                reference_obj = webapp.ref.models.get(ref_id)
            elif ref_type == "prompts":
                reference_obj = webapp.ref.prompts.get(ref_id)
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid reference type: {ref_type}"
                )
            
            if not reference_obj:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"{ref_type} {ref_id} not found"
                )
            
            # Convert to dict
            data = reference_obj.to_dict()
            
            return {
                "id": ref_id,
                "type": ref_type,
                "data": data
            }
            
        except HTTPException:
            raise
        except Exception as e:
            webapp.bus.emit_sync(system_events.ErrorEvent(
                error=f"Failed to get {ref_type} {ref_id}",
                e=e,
                tb=None
            ))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to get {ref_type} {ref_id}"
            )
    
    @router.put("/update")
    async def update_reference(request: UpdateReferenceRequest, user: dict = Depends(webapp.get_current_user)):
        """
        Update a reference with new data.
        Saves to database and reloads in memory through ref.py.
        """
        try:
            ref_type = request.ref_type
            ref_id = request.ref_id
            data = request.data
            
            # Get reference class from registry
            if ref_type == "assistants":
                reference_class = ref.AssistantReference
                collection = webapp.ref.assistants
            elif ref_type == "models":
                reference_class = ref.ModelReference
                collection = webapp.ref.models
            elif ref_type == "prompts":
                reference_class = ref.PromptReference
                collection = webapp.ref.prompts
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid reference type: {ref_type}"
                )
            
            # Create new reference object from data
            updated_reference = reference_class.from_dict(data)
            
            # Update in memory
            collection[ref_id] = updated_reference
            
            # Save to database directly
            await webapp.ref.db.insert_reference(updated_reference)
            
            return {
                "success": True,
                "message": f"{ref_type} {ref_id} updated successfully",
                "data": updated_reference.to_dict()
            }
            
        except HTTPException:
            raise
        except Exception as e:
            webapp.bus.emit_sync(system_events.ErrorEvent(
                error=f"Failed to update {request.ref_type} {request.ref_id}",
                e=e,
                tb=None
            ))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to update {request.ref_type}: {str(e)}"
            )
    
    @router.post("/reload")
    async def reload_references(user: dict = Depends(webapp.get_current_user)):
        """
        Reload all references from database.
        """
        try:
            webapp.ref._load()
            
            return {
                "success": True,
                "message": "References reloaded successfully"
            }
            
        except Exception as e:
            webapp.bus.emit_sync(system_events.ErrorEvent(
                error="Failed to reload references",
                e=e,
                tb=None
            ))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to reload references"
            )
    
    return router