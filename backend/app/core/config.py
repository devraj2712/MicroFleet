import os
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "MicroFleet Intelligent Logistics"
    VERSION: str = "0.1.0"
    API_V1_STR: str = "/api/v1"
    DEBUG: bool = True
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    
    # Path to SQLite database
    DATABASE_URL: str = "sqlite:///./backend/data/microfleet.db"

    # Geospatial and OSM road network configuration
    OSM_GRAPHML_PATH: str = "backend/data/networks/mumbai_drive_network.graphml"
    OSM_METADATA_PATH: str = "backend/data/networks/mumbai_drive_network.meta.json"
    MAX_SNAP_DISTANCE_METERS: float = 1000.0
    DEFAULT_SPEED_FALLBACK_KPH: float = 25.0

    # Authentication & Security
    AUTH_MODE: str = "development"  # Options: "development" or "firebase"
    FIREBASE_SERVICE_ACCOUNT_PATH: Optional[str] = None
    FIREBASE_PROJECT_ID: Optional[str] = None
    ADMIN_PROVISION_SECRET: str = "microfleet-admin-provision-secret-dev"
    DISPATCH_DRAFT_EXPIRY_MINUTES: int = 30
    
    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def sqlite_db_path(self) -> Path:
        """Resolve the local SQLite database file path and ensure directory exists."""
        if self.DATABASE_URL.startswith("sqlite:///"):
            clean_path = self.DATABASE_URL.replace("sqlite:///", "")
            path = Path(clean_path).resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            return path
        return Path("backend/data/microfleet.db").resolve()


settings = Settings()
