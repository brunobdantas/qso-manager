"""FastAPI application main entry point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os

from .core.config import settings
from .db.database import engine, Base
from .api import health, qsos, imports, reconciliation, backups, audit

# Create database tables
Base.metadata.create_all(bind=engine)

# Create FastAPI app
app = FastAPI(
    title="PU2BRU QSO Manager API",
    description="Backend API for QSO reconciliation and management",
    version="1.0.0",
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health.router)
app.include_router(qsos.router)
app.include_router(imports.router)
app.include_router(reconciliation.router)
app.include_router(backups.router)
app.include_router(audit.router)


@app.get("/")
def root():
    """Root endpoint with API information."""
    return {
        "name": "PU2BRU QSO Manager API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/api/health",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.backend_host,
        port=settings.backend_port,
        reload=settings.environment == "development",
    )
