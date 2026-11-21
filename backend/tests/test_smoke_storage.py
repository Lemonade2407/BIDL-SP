import jwt
import pytest

from backend.scripts.smoke_compose import invalid_download_url


def test_local_smoke_rejects_corrupted_signature(client, imported):
    """The local signature is in the path, so dropping a query must not be used."""
    signed_url = imported[1][0]["thumbnail_url"]
    assert client.get(signed_url).status_code == 200
    invalid_url = invalid_download_url(signed_url, "local")
    assert invalid_url != signed_url
    assert client.get(invalid_url).status_code == 403


def test_minio_smoke_removes_query_signature():
    signed_url = "http://localhost:9000/bidlsp-curated/image.png?X-Amz-Signature=test&X-Amz-Date=20261121"
    assert invalid_download_url(signed_url, "minio") == "http://localhost:9000/bidlsp-curated/image.png"
    with pytest.raises(ValueError, match="MinIO"):
        invalid_download_url("http://localhost:9000/bidlsp-curated/image.png", "minio")


def test_local_smoke_changes_signature_not_payload():
    token = jwt.encode({"kind": "object"}, "test-secret-only-000000000000000000000000", algorithm="HS256")
    invalid_url = invalid_download_url("http://localhost:8080/api/v1/files/" + token, "local")
    invalid_token = invalid_url.rsplit("/", 1)[1]
    assert invalid_token.rsplit(".", 1)[0] == token.rsplit(".", 1)[0]
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(invalid_token, "test-secret-only-000000000000000000000000", algorithms=["HS256"])
