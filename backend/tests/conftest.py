import io
import os
import tempfile
import zipfile
from pathlib import Path

TEST_ROOT = Path(__file__).resolve().parents[2] / ".runtime" / "tests"
TEST_ROOT.mkdir(parents=True, exist_ok=True)
TEMP = tempfile.TemporaryDirectory(prefix="run-", dir=TEST_ROOT, ignore_cleanup_errors=True)
os.environ.update(
    JWT_SECRET="test-secret-only-000000000000000000000000",
    STORAGE_BACKEND="local",
    STORAGE_DIR=str(Path(TEMP.name) / "objects"),
    WORK_DIR=str(Path(TEMP.name) / "work"),
    DATABASE_URL=os.environ.get("TEST_DATABASE_URL", "sqlite:///" + str(Path(TEMP.name) / "test.db")),
    TASK_EAGER="true",
    RATE_LIMIT_BACKEND="memory",
    PUBLIC_API_URL="http://testserver",
)

import numpy as np
import pytest
from alembic import command
from alembic.config import Config
from app import models as m
from app.cli import seed_admin
from app.db import SessionLocal, engine
from app.main import app
from app.security import _attempts, token
from app.storage import storage
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select


@pytest.fixture(autouse=True)
def database():
    engine.dispose()
    db_file = Path(TEMP.name) / "test.db"
    for suffix in ("", "-wal", "-shm"):
        Path(str(db_file) + suffix).unlink(missing_ok=True)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    if engine.dialect.name == "postgresql":
        assert engine.url.database == "bidlsp_test", "Refuse to reset a non-test PostgreSQL database"
        command.downgrade(config, "base")
    command.upgrade(config, "head")
    storage.init()
    _attempts.clear()
    with SessionLocal() as db:
        seed_admin(db, "DemoPassword!123", demo=True)
    yield
    engine.dispose()


@pytest.fixture
def client():
    with TestClient(app) as client:
        yield client


@pytest.fixture
def headers():
    with SessionLocal() as db:
        return {u.username: {"Authorization": "Bearer " + token(u)} for u in db.scalars(select(m.User))}


def png_bytes(array):
    output = io.BytesIO()
    Image.fromarray(array.astype("uint8")).save(output, "PNG")
    return output.getvalue()


def archive_bytes(count=7):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for c, label in enumerate(("benign", "malignant", "normal")):
            for i in range(1, count + 1):
                rng = np.random.default_rng(c * 100 + i)
                image = rng.integers(0, 256, (12, 16), dtype="uint8")
                mask = np.zeros((12, 16), dtype="uint8")
                if label != "normal":
                    mask[2:5, 3:8] = 255
                name = f"{label}/{label} ({i})"
                archive.writestr(name + ".png", png_bytes(image))
                archive.writestr(name + "_mask.png", png_bytes(mask))
    return output.getvalue()


@pytest.fixture
def imported(client, headers):
    from app.worker import drain_eager

    h = headers["admin"]
    response = client.post("/api/v1/datasets", headers=h, json={"name": "BUSI"})
    assert response.status_code == 201, response.text
    id = response.json()["data"]["id"]
    response = client.post(
        f"/api/v1/datasets/{id}/imports",
        headers=h,
        files={"file": ("busi.zip", archive_bytes(), "application/zip")},
    )
    assert response.status_code == 202, response.text
    drain_eager()
    job = client.get("/api/v1/imports/" + response.json()["data"]["job_id"], headers=h).json()["data"]
    assert job["success"] == 21, job
    images = client.get("/api/v1/images?page_size=100", headers=h).json()["data"]
    return id, images
