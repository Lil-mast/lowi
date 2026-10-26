"""Object storage with local-disk and S3-compatible backends."""

from __future__ import annotations

import hashlib
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol

import boto3
from botocore.config import Config

from app.config import Settings

CHUNK_SIZE = 1024 * 1024


class StorageError(Exception):
    """A storage operation failed."""


class UploadTooLarge(StorageError):
    """The uploaded file exceeds the configured limit."""


@dataclass(frozen=True)
class StoredObject:
    backend: str
    key: str
    size_bytes: int
    checksum_sha256: str
    content_type: str


class _HashingReader:
    """Wrap a binary stream and track its size and SHA-256 while it is read."""

    def __init__(self, raw: BinaryIO) -> None:
        self.raw = raw
        self.size = 0
        self.digest = hashlib.sha256()

    def read(self, size: int = -1) -> bytes:
        chunk = self.raw.read(size)
        if chunk:
            self.size += len(chunk)
            self.digest.update(chunk)
        return chunk

    def seek(self, offset: int, whence: int = 0) -> int:
        return self.raw.seek(offset, whence)

    def tell(self) -> int:
        return self.raw.tell()


class Storage(Protocol):
    backend: str

    def put(self, key: str, data: BinaryIO, content_type: str) -> StoredObject: ...

    def delete(self, key: str) -> None: ...

    def presigned_get(self, key: str, expires_in: int = 900) -> str | None: ...

    @contextmanager
    def materialize(self, key: str) -> Iterator[Path]: ...


class LocalStorage:
    backend = "local"

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root not in path.parents and path != self.root:
            raise StorageError("Invalid storage key")
        return path

    def put(self, key: str, data: BinaryIO, content_type: str) -> StoredObject:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        reader = _HashingReader(data)
        with path.open("wb") as destination:
            while chunk := reader.read(CHUNK_SIZE):
                destination.write(chunk)
        return StoredObject(
            backend=self.backend,
            key=key,
            size_bytes=reader.size,
            checksum_sha256=reader.digest.hexdigest(),
            content_type=content_type,
        )

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def presigned_get(self, key: str, expires_in: int = 900) -> str | None:
        return None

    @contextmanager
    def materialize(self, key: str) -> Iterator[Path]:
        path = self._path(key)
        if not path.exists():
            raise StorageError("Stored object not found")
        yield path


class S3Storage:
    backend = "s3"

    def __init__(self, settings: Settings) -> None:
        self.bucket = settings.s3_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url or None,
            region_name=settings.s3_region or None,
            aws_access_key_id=settings.s3_access_key_id or None,
            aws_secret_access_key=settings.s3_secret_access_key or None,
            config=Config(
                s3={"addressing_style": "path" if settings.s3_force_path_style else "auto"},
                signature_version="s3v4",
            ),
        )

    def put(self, key: str, data: BinaryIO, content_type: str) -> StoredObject:
        reader = _HashingReader(data)
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=reader,
                ContentType=content_type,
            )
        except Exception as exc:
            raise StorageError("Could not upload object") from exc
        return StoredObject(
            backend=self.backend,
            key=key,
            size_bytes=reader.size,
            checksum_sha256=reader.digest.hexdigest(),
            content_type=content_type,
        )

    def delete(self, key: str) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            raise StorageError("Could not delete object") from exc

    def presigned_get(self, key: str, expires_in: int = 900) -> str | None:
        try:
            return self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=expires_in,
            )
        except Exception as exc:
            raise StorageError("Could not create a download URL") from exc

    @contextmanager
    def materialize(self, key: str) -> Iterator[Path]:
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            path = Path(handle.name)
            try:
                self.client.download_fileobj(self.bucket, key, handle)
            except Exception:
                path.unlink(missing_ok=True)
                raise
        try:
            yield path
        finally:
            path.unlink(missing_ok=True)


def store_upload(
    storage: Storage,
    key: str,
    source: BinaryIO,
    *,
    content_type: str,
    max_bytes: int,
) -> StoredObject:
    """Spool an upload to a bounded temp file before handing it to storage."""
    with tempfile.SpooledTemporaryFile(max_size=8 * CHUNK_SIZE) as spool:
        size = 0
        while chunk := source.read(CHUNK_SIZE):
            size += len(chunk)
            if size > max_bytes:
                raise UploadTooLarge(f"File exceeds the {max_bytes // (1024 * 1024)} MB limit")
            spool.write(chunk)
        if size == 0:
            raise StorageError("Empty upload")
        spool.seek(0)
        return storage.put(key, spool, content_type)


def build_storage(settings: Settings) -> Storage:
    if settings.storage_backend == "s3":
        return S3Storage(settings)
    return LocalStorage(settings.data_dir)


def audio_key(meeting_id: str, recording_id: str, filename: str) -> str:
    suffix = Path(filename).suffix.lower() or ".bin"
    return f"meetings/{meeting_id}/recordings/{recording_id}{suffix}"
