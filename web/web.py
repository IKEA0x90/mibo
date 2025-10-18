"""
Main webapp using FastAPI with async support.
IS NOT the entry point - entry point is still mibo.py.
This webapp integrates with the existing mibo bot infrastructure.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
import uvicorn
from pathlib import Path
import os

from fastapi import FastAPI, Request, Response, HTTPException, Depends, status, Form
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt

from events import event_bus
from core import ref
from services import variables
from .auth import authentication
from .dashboard import dashboard

class WebApp:
    def __init__(self, ref_instance: ref.Ref, bus_instance: event_bus.EventBus):
        """
        Initialize the web application with shared ref and event bus instances.
        """
        self.ref = ref_instance
        self.bus = bus_instance
        
        # FastAPI app instance
        self.app = FastAPI(
            title="Mibo Admin Panel",
            description="Admin control panel for Mibo chatbot",
            version="1.0.0"
        )
        
        # JWT Configuration
        self.JWT_SECRET = variables.Variables.JWT_SECRET_KEY
        self.JWT_ALGORITHM = "HS256"
        self.JWT_EXPIRE_MINUTES = 30
        
        # Security
        self.security = HTTPBearer(auto_error=False)
        
        # Templates and static files setup
        self.templates = Jinja2Templates(directory="web")
        
        self._setup_middleware()
        self._setup_routes()
        
    def _setup_middleware(self):
        """Setup CORS and security middleware for HTTPS deployment."""
        # Get domain from environment or use default
        domain = variables.Variables.MIBO_DOMAIN
        
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=[
                f"https://{domain}",
                f"https://www.{domain}",
                "http://localhost:6426",  # For local testing
                "http://127.0.0.1:6426",  # Local testing alternative
            ],
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-Requested-With", "Accept"],
        )
        
        @self.app.middleware("http")
        async def security_headers(request: Request, call_next):
            response = await call_next(request)
            
            # HTTPS Security Headers for subdomain
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["X-XSS-Protection"] = "1; mode=block"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            
            # HSTS for subdomain (always set since we're HTTPS-only)
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
            
            # Content Security Policy for admin subdomain
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data:; "
                "font-src 'self'; "
                "connect-src 'self';"
            )
            
            return response
    
    def _setup_routes(self):
        """Setup all application routes."""
        
        # Mount static files
        self.app.mount("/static", StaticFiles(directory="web"), name="static")
        
        # Include authentication and dashboard routers
        auth_router = authentication.create_auth_router(self)
        dashboard_router = dashboard.create_dashboard_router(self)
        
        self.app.include_router(auth_router, prefix="/api/auth", tags=["authentication"])
        self.app.include_router(dashboard_router, prefix="/api/dashboard", tags=["dashboard"])
        
        # Root redirect to login
        @self.app.get("/", response_class=RedirectResponse)
        async def root():
            return RedirectResponse(url="/login", status_code=302)
        
        # Login page
        @self.app.get("/login", response_class=HTMLResponse)
        async def login_page(request: Request):
            return self.templates.TemplateResponse("auth/login.html", {"request": request})
        
        # Dashboard page (public access - auth handled by JavaScript)
        @self.app.get("/dashboard", response_class=HTMLResponse)
        async def dashboard_page(request: Request):
            return self.templates.TemplateResponse("dashboard/dashboard.html", {
                "request": request
            })
    
    def create_access_token(self, data: dict) -> str:
        """Create a JWT access token."""
        to_encode = data.copy()
        expire = datetime.now(timezone.utc) + timedelta(minutes=self.JWT_EXPIRE_MINUTES)
        to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc)})
        
        encoded_jwt = jwt.encode(to_encode, self.JWT_SECRET, algorithm=self.JWT_ALGORITHM)
        return encoded_jwt
    
    def verify_token(self, token: str) -> Optional[dict]:
        """Verify and decode a JWT token."""
        try:
            payload = jwt.decode(token, self.JWT_SECRET, algorithms=[self.JWT_ALGORITHM])
            return payload
        except jwt.ExpiredSignatureError:
            print(f"JWT token expired: {token[:20]}...")
            return None
        except jwt.JWTError as e:
            print(f"JWT decode error: {e}, token: {token[:20]}...")
            return None
    
    async def get_current_user(self, credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer(auto_error=False))):
        """Dependency to get current authenticated user."""
        if not credentials:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        token = credentials.credentials
        payload = self.verify_token(token)
        
        if payload is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        user_id = payload.get("user_id")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload",
            )
        
        # Get user from ref
        try:
            user = await self.ref.get_user(user_id)
            if not user or not user.password:  # Check if user has password (is registered)
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User not found or not registered",
                )
            
            return {
                "user_id": user.id,
                "username": user.username,
                "admin_chats": getattr(user, 'admin_chats', [])
            }
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User verification failed",
            )

async def start_webapp(ref_instance: ref.Ref, bus_instance: event_bus.EventBus, port: int = 6426):
    """
    Start the web application server.
    This function should be called from mibo.py to integrate with the main bot.
    """
    webapp = WebApp(ref_instance, bus_instance)
    
    config = uvicorn.Config(
        app=webapp.app,
        host="0.0.0.0",
        port=port,
        log_level="info",
        access_log=True
    )
    
    server = uvicorn.Server(config)
    await server.serve()