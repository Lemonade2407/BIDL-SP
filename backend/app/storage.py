import hashlib
import io
from datetime import timedelta
from pathlib import Path, PurePosixPath
from urllib.parse import quote

import jwt
import urllib3
from minio import Minio

from .common import APIError
from .config import settings
from .db import now

BUCKETS = tuple("bidlsp-" + x for x in ("raw", "curated", "dataset", "model", "result", "report"))


class Storage:
    def __init__(self):
        self.local = settings.storage_backend == "local"
        if not self.local:
            self.client = Minio(
                settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=settings.minio_secure,
                http_client=urllib3.PoolManager(timeout=urllib3.Timeout(connect=3, read=60), retries=2),
            )
            self.public = Minio(
                settings.minio_public_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=settings.minio_secure,
                region="us-east-1",
            )

    def path(self, bucket, key):
        if bucket not in BUCKETS or not key or "\\" in key or "\x00" in key:
            raise APIError(422, "非法对象键")
        parts = PurePosixPath(key)
        if parts.is_absolute() or ".." in parts.parts or ":" in key:
            raise APIError(422, "非法对象键")
        root = settings.storage_dir.resolve()
        result = (root / bucket / key).resolve()
        if not result.is_relative_to(root):
            raise APIError(422, "非法对象键")
        return result

    def init(self):
        for bucket in BUCKETS:
            if self.local:
                (settings.storage_dir / bucket).mkdir(parents=True, exist_ok=True)
            elif not self.client.bucket_exists(bucket):
                self.client.make_bucket(bucket)

    def put(self, bucket, key, data, content_type="application/octet-stream"):
        path = self.path(bucket, key)
        if self.local:
            path.parent.mkdir(parents=True, exist_ok=True)
            # O_EXCL guarantees objects are never silently overwritten.
            try:
                with path.open("xb") as stream:
                    stream.write(data)
            except FileExistsError:
                if path.read_bytes() != data:
                    raise APIError(409, "对象不可覆盖") from None
        else:
            self.client.put_object(bucket, key, io.BytesIO(data), len(data), content_type=content_type)
        return key

    def put_file(self, bucket, key, path, content_type="application/octet-stream"):
        self.path(bucket, key)
        if self.local:
            import shutil

            target = self.path(bucket, key)
            target.parent.mkdir(parents=True, exist_ok=True)
            with Path(path).open("rb") as source, target.open("xb") as dest:
                shutil.copyfileobj(source, dest)
        else:
            self.client.fput_object(bucket, key, str(path), content_type=content_type)

    def read(self, bucket, key):
        path = self.path(bucket, key)
        if self.local:
            if not path.is_file():
                raise APIError(404, "对象不存在")
            return path.read_bytes()
        try:
            response = self.client.get_object(bucket, key)
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()
        except Exception:
            raise APIError(503, "对象存储读取失败") from None

    def download(self, bucket, key, target):
        self.path(bucket, key)
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        if self.local:
            import shutil

            shutil.copyfile(self.path(bucket, key), target)
        else:
            self.client.fget_object(bucket, key, str(target))
        return target

    def sha256(self, bucket, key):
        path = self.path(bucket, key)
        stream = path.open("rb") if self.local else self.client.get_object(bucket, key)
        try:
            digest = hashlib.sha256()
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
            return digest.hexdigest()
        finally:
            stream.close()
            if not self.local:
                stream.release_conn()

    def url(self, bucket, key):
        self.path(bucket, key)
        if self.local:
            signed = jwt.encode(
                {"kind": "object", "bucket": bucket, "key": key, "exp": now() + timedelta(seconds=300)},
                settings.jwt_secret,
                algorithm="HS256",
            )
            return settings.public_api_url.rstrip("/") + "/api/v1/files/" + quote(signed, safe="")
        return self.public.presigned_get_object(bucket, key, expires=timedelta(seconds=300))

    def health(self):
        if self.local:
            return settings.storage_dir.is_dir()
        return all(self.client.bucket_exists(b) for b in BUCKETS)


storage = Storage()
