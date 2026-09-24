"""Google Calendar connect and upcoming-event list."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse

from app.api.deps import get_settings
from app.config import Settings
from app.services.calendar import (
    CalendarNotConfigured,
    CalendarNotConnected,
    authorization_url,
    exchange_code,
    google_configured,
    list_upcoming_events,
)

router = APIRouter(tags=["calendar"])


@router.get("/calendar/connect")
def connect(settings: Settings = Depends(get_settings)) -> RedirectResponse:
    try:
        return RedirectResponse(authorization_url(settings))
    except CalendarNotConfigured as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/calendar/callback", response_class=HTMLResponse)
def callback(
    code: str = Query(...),
    state: str = Query(...),
    settings: Settings = Depends(get_settings),
) -> str:
    try:
        exchange_code(settings, code, state)
    except (CalendarNotConfigured, ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return "<p>Google Calendar is connected. Return to LoWi.</p>"


@router.get("/calendar/events")
def events(settings: Settings = Depends(get_settings)) -> dict:
    if not google_configured(settings):
        return {"configured": False, "connected": False, "events": []}
    try:
        items = list_upcoming_events(settings, datetime.now(UTC))
    except CalendarNotConnected:
        return {"configured": True, "connected": False, "events": []}
    return {"configured": True, "connected": True, "events": items}
