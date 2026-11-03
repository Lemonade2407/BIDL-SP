"""Exercise the running Compose deployment with synthetic, non-clinical data.

Requires development dependencies. Uses the generated deploy/.env password locally
without printing credentials. Beat, dispatcher and worker must process the outbox;
this script never executes jobs eagerly or calls dispatch directly.
"""

import io
import time
import zipfile
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx
from PIL import Image


def main():
    root = Path(__file__).resolve().parents[2]
    env = dict(
        line.split("=", 1)
        for line in (root / "deploy/.env").read_text().splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    with httpx.Client(base_url="http://localhost:8080/api/v1", timeout=20) as api:
        response = api.post("/auth/login", json={"username": "admin", "password": env["ADMIN_PASSWORD"]})
        response.raise_for_status()
        api.headers["Authorization"] = "Bearer " + response.json()["data"]["access_token"]
        response = api.post("/datasets", json={"name": "compose-smoke"})
        response.raise_for_status()
        dataset_id = response.json()["data"]["id"]
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zipped:
            for suffix, value in (("", 127), ("_mask", 0)):
                png = io.BytesIO()
                Image.new("L", (32, 32), value).save(png, "PNG")
                zipped.writestr(f"normal/normal (1){suffix}.png", png.getvalue())
        response = api.post(
            f"/datasets/{dataset_id}/imports",
            files={"file": ("smoke.zip", archive.getvalue(), "application/zip")},
        )
        response.raise_for_status()
        job_id = response.json()["data"]["job_id"]
        deadline = time.monotonic() + 90
        while True:
            response = api.get(f"/imports/{job_id}")
            response.raise_for_status()
            job = response.json()["data"]
            if job["status"] in ("completed", "failed"):
                break
            if time.monotonic() >= deadline:
                raise RuntimeError(f"Asynchronous import timed out: {job['status']}")
            time.sleep(2)
        assert job["success"] == 1 and job["failed"] == 0, job
        response = api.get("/images", params={"dataset_id": dataset_id})
        response.raise_for_status()
        images = response.json()["data"]
        assert len(images) == 1, images
        signed_url = images[0]["thumbnail_url"]
        # Use a separate unauthenticated client: S3 access depends on the signature.
        with httpx.Client(timeout=20) as objects:
            response = objects.get(signed_url)
            response.raise_for_status()
            Image.open(io.BytesIO(response.content)).verify()
            parts = urlsplit(signed_url)
            unsigned_url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
            assert objects.get(unsigned_url).status_code == 403
        print("PASS: API -> PostgreSQL outbox -> Beat/dispatcher -> Redis -> Worker -> private MinIO")


if __name__ == "__main__":
    main()
