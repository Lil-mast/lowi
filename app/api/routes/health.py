"""Health check and API index."""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["health"])


@router.get("/", response_class=HTMLResponse)
def index() -> str:
    return """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>LoWi</title></head>
<body>
  <h1>LoWi</h1>
  <p>This process is the API. The app UI is Streamlit (<code>uv run streamlit run frontend/app.py</code>).</p>
  <ul>
    <li><a href="/docs">API docs</a></li>
    <li><a href="/health">Health</a></li>
    <li><a href="/meetings">Meetings</a></li>
    <li><a href="/action-items">Open action items</a></li>
  </ul>
</body>
</html>
"""


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
