"""Read-only Google Calendar. Tokens stay on disk or in GOOGLE_REFRESH_TOKEN."""

import json
from datetime import datetime

from app.config import Settings

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


class CalendarNotConfigured(Exception):
    """Google client id and secret are missing."""


class CalendarNotConnected(Exception):
    """OAuth has not been completed for this install."""


def google_configured(settings: Settings) -> bool:
    return bool(settings.google_client_id and settings.google_client_secret)


def token_path(settings: Settings):
    return settings.data_dir / "google_token.json"


def state_path(settings: Settings):
    return settings.data_dir / "google_oauth_state.txt"


def _client_config(settings: Settings) -> dict:
    return {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.google_redirect_uri],
        }
    }


def authorization_url(settings: Settings) -> str:
    if not google_configured(settings):
        raise CalendarNotConfigured("Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET")
    from google_auth_oauthlib.flow import Flow

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    flow = Flow.from_client_config(_client_config(settings), scopes=SCOPES)
    flow.redirect_uri = settings.google_redirect_uri
    url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    state_path(settings).write_text(state)
    return url


def exchange_code(settings: Settings, code: str, state: str) -> None:
    if not google_configured(settings):
        raise CalendarNotConfigured("Google Calendar is not configured")
    expected = state_path(settings).read_text() if state_path(settings).exists() else ""
    if not expected or state != expected:
        raise ValueError("OAuth state mismatch")
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_config(_client_config(settings), scopes=SCOPES)
    flow.redirect_uri = settings.google_redirect_uri
    flow.fetch_token(code=code)
    creds = flow.credentials
    payload = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or SCOPES),
    }
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    token_path(settings).write_text(json.dumps(payload))


def event_to_item(item: dict) -> dict:
    start = item.get("start") or {}
    return {
        "id": item.get("id") or "",
        "title": item.get("summary") or "(no title)",
        "start": start.get("dateTime") or start.get("date"),
        "agenda": item.get("description") or "",
        "html_link": item.get("htmlLink"),
    }


def list_upcoming_events(settings: Settings, now: datetime) -> list[dict]:
    if not google_configured(settings):
        raise CalendarNotConfigured("Google Calendar is not configured")
    path = token_path(settings)
    if path.exists():
        info = json.loads(path.read_text())
    elif settings.google_refresh_token:
        info = {
            "refresh_token": settings.google_refresh_token,
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "scopes": SCOPES,
        }
    else:
        raise CalendarNotConnected("Connect Google Calendar first")

    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_authorized_user_info(info, SCOPES)
    service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=now.isoformat(),
            maxResults=10,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    return [event_to_item(item) for item in result.get("items", [])]
