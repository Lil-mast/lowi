from __future__ import annotations

import io

import pytest
from app.config import Settings
from app.services.storage import (
    LocalStorage,
    S3Storage,
    StorageError,
    UploadTooLarge,
    audio_key,
    store_upload,
)


def test_local_storage_round_trip(tmp_path):
    storage = LocalStorage(tmp_path)
    stored = storage.put("meetings/m1/audio.mp3", io.BytesIO(b"hello"), "audio/mpeg")

    assert stored.backend == "local"
    assert stored.size_bytes == 5
    assert stored.checksum_sha256 == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    with storage.materialize("meetings/m1/audio.mp3") as path:
        assert path.read_bytes() == b"hello"
    assert storage.presigned_get("meetings/m1/audio.mp3") is None

    storage.delete("meetings/m1/audio.mp3")
    with pytest.raises(StorageError), storage.materialize("meetings/m1/audio.mp3"):
        pass


def test_local_storage_rejects_path_traversal(tmp_path):
    storage = LocalStorage(tmp_path / "root")
    with pytest.raises(StorageError, match="Invalid storage key"):
        storage.put("../escape.txt", io.BytesIO(b"no"), "text/plain")


def test_store_upload_enforces_limit(tmp_path):
    storage = LocalStorage(tmp_path)
    with pytest.raises(UploadTooLarge):
        store_upload(
            storage,
            "big.bin",
            io.BytesIO(b"x" * 10),
            content_type="application/octet-stream",
            max_bytes=5,
        )


def test_store_upload_rejects_empty_file(tmp_path):
    storage = LocalStorage(tmp_path)
    with pytest.raises(StorageError, match="Empty upload"):
        store_upload(
            storage,
            "empty.bin",
            io.BytesIO(b""),
            content_type="application/octet-stream",
            max_bytes=100,
        )


def test_audio_key_uses_a_safe_extension():
    assert audio_key("m1", "r1", "My Recording.MP3") == "meetings/m1/recordings/r1.mp3"
    assert audio_key("m1", "r1", "no-extension") == "meetings/m1/recordings/r1.bin"


def test_s3_presigned_urls_use_signature_v4():
    storage = S3Storage(
        Settings(
            _env_file=None,
            s3_bucket="bucket",
            s3_region="us-east-1",
            s3_endpoint_url="https://storage.example",
            s3_access_key_id="key",
            s3_secret_access_key="secret",
            s3_force_path_style=True,
        )
    )
    url = storage.presigned_get("meetings/m1/audio.wav")
    assert url is not None
    assert "X-Amz-Algorithm=" in url
    assert "X-Amz-Signature=" in url
