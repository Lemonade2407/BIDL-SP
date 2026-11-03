from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
DISCLAIMER = "仅供科研/教学使用，不作为临床诊断依据"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "sqlite:///./bidlsp.db"
    jwt_secret: str = Field(min_length=32)
    jwt_hours: int = Field(default=8, ge=1, le=8)
    redis_url: str = "redis://localhost:6379/0"
    storage_backend: str = "minio"
    storage_dir: Path = ROOT / ".runtime" / "objects"
    work_dir: Path = ROOT / ".runtime" / "work"
    minio_endpoint: str = "localhost:9000"
    minio_public_endpoint: str = "localhost:9000"
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_secure: bool = False
    public_api_url: str = "http://localhost:8000"
    task_eager: bool = False
    rate_limit_backend: str = "redis"
    max_upload_mb: int = 20
    max_zip_mb: int = 2048
    device: str = "cpu"
    pdf_font_path: str = ""
    cors_origins: list[str] = ["http://localhost:5173"]


settings = Settings()
