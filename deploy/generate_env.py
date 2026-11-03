"""Create a local untracked environment without printing secrets."""

import secrets
from pathlib import Path

target = Path(__file__).with_name(".env")
values = {
    "POSTGRES_PASSWORD": secrets.token_urlsafe(24),
    "MINIO_ROOT_USER": "bidlsp",
    "MINIO_ROOT_PASSWORD": secrets.token_urlsafe(24),
    "JWT_SECRET": secrets.token_urlsafe(48),
    "ADMIN_PASSWORD": secrets.token_urlsafe(18),
    "MINIO_PUBLIC_ENDPOINT": "localhost:9000",
    "PUBLIC_API_URL": "http://localhost:8080",
    "CORS_ORIGINS": '["http://localhost:5173"]',
}
with target.open("x", encoding="utf-8") as stream:
    stream.write("\n".join(f"{key}={value}" for key, value in values.items()) + "\n")
print(f"Created {target}; inspect ADMIN_PASSWORD locally. Existing files are never overwritten.")
