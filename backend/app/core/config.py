import os
from pathlib import Path
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
