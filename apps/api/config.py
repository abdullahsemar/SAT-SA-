import os
from pathlib import Path

from pydantic import BaseModel


class AppConfig(BaseModel):
    environment: str = os.getenv("ENVIRONMENT", "development")
    host: str = os.getenv("HOST", "127.0.0.1")
    port: int = int(os.getenv("PORT", "8000"))
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///storage/sat_sa.db")
    storage_dir: str = os.getenv("STORAGE_DIR", "storage/raw_files")
    session_secret: str = os.getenv("SESSION_SECRET", "super-secret-session-key-dev-only-32chars!")
    session_max_age_seconds: int = int(os.getenv("SESSION_MAX_AGE_SECONDS", "86400"))  # 24h
    max_upload_size_bytes: int = int(os.getenv("MAX_UPLOAD_SIZE_BYTES", str(50 * 1024 * 1024)))
    max_row_size_bytes: int = int(os.getenv("MAX_ROW_SIZE_BYTES", str(64 * 1024)))


settings = AppConfig()

# Ensure storage directories exist
Path(settings.storage_dir).mkdir(parents=True, exist_ok=True)
