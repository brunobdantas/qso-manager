"""FastAPI application main entry point."""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .core.config import settings
from .db.database import engine, Base
from .api import health, qsos, imports, reconciliation, backups, audit

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="PU2BRU QSO Manager API",
    description="Backend API for QSO reconciliation and management",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(qsos.router)
app.include_router(imports.router)
app.include_router(reconciliation.router)
app.include_router(backups.router)
app.include_router(audit.router)

ROOT_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIST = ROOT_DIR / "frontend" / "dist"
ASSETS_DIR = FRONTEND_DIST / "assets"

if ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")


@app.get("/", include_in_schema=False)
def root():
    index = FRONTEND_DIST / "index.html"
    if index.exists():
        return FileResponse(index)
    return {
        "name": "PU2BRU QSO Manager API",
        "version": "2.0.0",
        "docs": "/docs",
        "health": "/api/health",
        "frontend": "not-built",
    }


@app.get("/{full_path:path}", include_in_schema=False)
def spa_fallback(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API endpoint not found")
    index = FRONTEND_DIST / "index.html"
    if index.exists():
        return FileResponse(index)
    raise HTTPException(status_code=404, detail="Frontend not built. Run setup.ps1 or npm run build.")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.backend_host,
        port=settings.backend_port,
        reload=settings.environment == "development",
    )
