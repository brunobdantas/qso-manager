from pydantic_settings import BaseSettings
from typing import Optional
import os


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Database
    database_url: str = "sqlite:///./data/qso_manager.db"
    
    # QRZ.com API
    qrz_api_key: Optional[str] = None
    qrz_username: Optional[str] = None
    
    # Server
    backend_host: str = "127.0.0.1"
    backend_port: int = 8000
    frontend_port: int = 5173
    
    # Environment
    environment: str = "development"
    
    # CORS
    cors_origins: list = ["http://localhost:5173", "http://127.0.0.1:5173"]
    
    class Config:
        env_file = ".env"
        case_sensitive = False
    
    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"
    
    @property
    def qrz_enabled(self) -> bool:
        return bool(self.qrz_api_key and self.qrz_username)


settings = Settings()
