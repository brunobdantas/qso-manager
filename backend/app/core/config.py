"""Core configuration and settings."""
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings."""
    
    # Database
    database_url: str = "sqlite:///./data/qso_manager.db"
    
    # API
    api_title: str = "PU2BRU QSO Manager API"
    api_version: str = "1.0.0"
    
    # Frequency tolerance in Hz
    freq_tolerance_hz: int = 1000
    
    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
