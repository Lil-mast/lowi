"""Local file storage. R2/S3 is deferred."""

from pathlib import Path


def save_audio(data_dir: Path, meeting_id: str, filename: str, content: bytes) -> Path:
    folder = data_dir / meeting_id
    folder.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename).name or "audio.bin"
    path = folder / safe_name
    path.write_bytes(content)
    return path
