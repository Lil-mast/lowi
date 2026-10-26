"""Streamlit UI. Calls the FastAPI backend; no business logic here."""

from __future__ import annotations

import os
from contextlib import suppress
from datetime import datetime
from pathlib import Path

import httpx
import streamlit as st
from extra_streamlit_components import CookieManager

API_URL = os.environ.get("LOWI_API_URL", "http://127.0.0.1:8000").rstrip("/")
COOKIE_NAME = "lowi_session"

STATUS_COLOR = {
    "scheduled": "gray",
    "uploaded": "blue",
    "transcribed": "blue",
    "summarized": "green",
    "sent": "green",
    "failed": "red",
}


@st.cache_resource
def http_client() -> httpx.Client:
    return httpx.Client(base_url=API_URL, timeout=120)


@st.cache_resource
def cookie_manager() -> CookieManager:
    return CookieManager(key="lowi_cookies")


def request(method: str, path: str, *, auth_required: bool = True, **kwargs) -> httpx.Response:
    token = st.session_state.get("token")
    if auth_required and token:
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = f"Bearer {token}"
        kwargs["headers"] = headers
    response = http_client().request(method, path, **kwargs)
    if auth_required and response.status_code == 401:
        clear_session()
        st.rerun()
    return response


def error_text(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail", response.text)
    except ValueError:
        return response.text
    if isinstance(detail, list):
        return "; ".join(str(item.get("msg", item)) for item in detail)
    return str(detail)


def store_session(body: dict) -> None:
    st.session_state["token"] = body["token"]
    st.session_state["user"] = body["user"]
    expires_at = body.get("expires_at")
    if expires_at:
        with suppress(Exception):
            parsed = datetime.fromisoformat(expires_at)
            cookie_manager().set(COOKIE_NAME, body["token"], expires_at=parsed)
    st.rerun()


def clear_session() -> None:
    st.session_state.pop("token", None)
    st.session_state.pop("user", None)
    st.session_state.pop("pdf_bytes", None)
    with suppress(Exception):
        cookie_manager().delete(COOKIE_NAME)


def login_screen() -> None:
    st.subheader("Sign in")
    sign_in, create = st.tabs(["Sign in", "Create account"])

    with sign_in:
        with st.form("sign-in"):
            email = st.text_input("Email", key="login-email")
            password = st.text_input("Password", type="password", key="login-password")
            submitted = st.form_submit_button(
                "Sign in", icon=":material/login:", type="primary"
            )
        if submitted:
            response = request(
                "POST",
                "/auth/login",
                auth_required=False,
                json={"email": email.strip(), "password": password},
            )
            if response.is_error:
                st.error(error_text(response))
            else:
                store_session(response.json())

    with create:
        with st.form("create-account"):
            name = st.text_input("Name", key="register-name")
            email = st.text_input("Email", key="register-email")
            password = st.text_input(
                "Password",
                type="password",
                key="register-password",
                help="At least 8 characters.",
            )
            submitted = st.form_submit_button(
                "Create account", icon=":material/person_add:", type="primary"
            )
        if submitted:
            if not name.strip():
                st.warning("Add your name first.")
            else:
                response = request(
                    "POST",
                    "/auth/register",
                    auth_required=False,
                    json={
                        "email": email.strip(),
                        "password": password,
                        "name": name.strip(),
                    },
                )
                if response.is_error:
                    st.error(error_text(response))
                else:
                    store_session(response.json())


logo = Path(__file__).parent / "bot.png"
st.set_page_config(
    page_title="LoWi",
    page_icon=str(logo) if logo.exists() else ":material/graphic_eq:",
    layout="centered",
)
if logo.exists():
    st.logo(str(logo))
st.title("LoWi", help="Meeting notes")
st.caption(f"API {API_URL}")

try:
    health = request("GET", "/health", auth_required=False)
    health.raise_for_status()
except httpx.HTTPError as exc:
    st.error(f"API is not reachable at {API_URL}. Start it with `uv run uvicorn app.main:app --reload`.")
    st.caption(str(exc))
    st.stop()

config_response = request("GET", "/auth/config", auth_required=False)
auth_config = config_response.json() if config_response.is_success else {"required": False}
auth_required = bool(auth_config.get("required"))

user = st.session_state.get("user")
if auth_required:
    token = st.session_state.get("token")
    if not token:
        try:
            token = cookie_manager().get(COOKIE_NAME)
        except Exception:  # noqa: BLE001 - cookie persistence is best effort
            token = None
        if token:
            st.session_state["token"] = token

    if not st.session_state.get("token"):
        login_screen()
        st.stop()

    me = request("GET", "/auth/me")
    if me.is_error:
        clear_session()
        st.rerun()
    user = me.json()
    st.session_state["user"] = user


with st.sidebar:
    if auth_required and user:
        st.caption(f"Signed in as {user['name']}")
        st.caption(user["email"])
        if st.button("Sign out", icon=":material/logout:"):
            request("POST", "/auth/logout")
            clear_session()
            st.rerun()

    st.header("Meetings")
    listed = request("GET", "/meetings")
    meetings = listed.json() if listed.is_success else []
    if meetings:
        labels = {f"{item['title']} ({item['status']})": item["id"] for item in meetings}
        default_id = st.session_state.get("meeting_id", meetings[0]["id"])
        default_label = next(
            (label for label, value in labels.items() if value == default_id),
            next(iter(labels)),
        )
        choice = st.selectbox("Meeting", list(labels), index=list(labels).index(default_label))
        st.session_state["meeting_id"] = labels[choice]
    else:
        st.caption("No meetings yet.")

calendar = request("GET", "/calendar/events")
with st.container(border=True):
    st.subheader("Upcoming on Google Calendar")
    if calendar.is_error:
        st.error(error_text(calendar))
    else:
        body = calendar.json()
        if not body["configured"]:
            st.caption("Add Google OAuth credentials on the API to list upcoming events.")
        elif not body["connected"]:
            st.link_button(
                "Connect Google Calendar",
                f"{API_URL}/calendar/connect",
                icon=":material/calendar_month:",
            )
        elif not body["events"]:
            st.caption("No upcoming events.")
        else:
            for event in body["events"]:
                when = event.get("start") or "unscheduled"
                st.markdown(f"**{event['title']}** · {when}")
                if event.get("agenda"):
                    st.caption(event["agenda"])
                if st.button(
                    "Prep this meeting",
                    key=f"cal-{event['id']}",
                    icon=":material/event:",
                ):
                    payload = {
                        "title": event["title"],
                        "calendar_event_id": event["id"],
                        "agenda": event.get("agenda") or None,
                        "generate_prep": True,
                    }
                    start = event.get("start") or ""
                    if "T" in start:
                        payload["scheduled_at"] = start
                    response = request("POST", "/meetings", json=payload)
                    if response.is_error:
                        st.error(error_text(response))
                    else:
                        st.session_state["meeting_id"] = response.json()["id"]
                        st.rerun()

with st.container(border=True):
    st.subheader("New meeting")
    with st.form("create-meeting", clear_on_submit=True):
        title = st.text_input("Title")
        agenda = st.text_area(
            "Agenda",
            placeholder="What should the brief prepare you for?",
        )
        generate_prep = st.checkbox("Generate prep brief", value=True)
        submitted = st.form_submit_button("Create", icon=":material/add:", type="primary")
    if submitted:
        if not title.strip():
            st.warning("Add a title first.")
        else:
            response = request(
                "POST",
                "/meetings",
                json={
                    "title": title.strip(),
                    "agenda": agenda.strip() or None,
                    "generate_prep": generate_prep,
                },
            )
            if response.is_error:
                st.error(error_text(response))
            else:
                st.session_state["meeting_id"] = response.json()["id"]
                st.rerun()

open_response = request("GET", "/action-items")
open_items = open_response.json() if open_response.is_success else []
with st.container(border=True):
    st.subheader("Open action items")
    if not open_items:
        st.caption("None yet.")
    else:
        for item in open_items:
            owner = f" — {item['owner']}" if item.get("owner") else ""
            st.markdown(f"- {item['description']}{owner}")

meeting_id = st.session_state.get("meeting_id")
if not meeting_id:
    st.info("Create a meeting to get started.")
    st.stop()

detail_response = request("GET", f"/meetings/{meeting_id}")
if detail_response.is_error:
    st.error(error_text(detail_response))
    st.stop()
detail = detail_response.json()

st.header(detail["title"])
st.badge(detail["status"], color=STATUS_COLOR.get(detail["status"], "gray"))
if detail.get("agenda"):
    st.markdown(detail["agenda"])
if detail.get("error"):
    st.error(detail["error"])

if detail.get("prep_brief"):
    with st.container(border=True):
        st.subheader("Prep", divider="gray")
        st.markdown(detail["prep_brief"])

with st.container(border=True):
    st.subheader("Audio", divider="gray")
    audio = st.file_uploader(
        "Audio file",
        type=["mp3", "wav", "m4a", "mp4", "webm", "ogg"],
        label_visibility="collapsed",
    )
    if st.button("Upload and process", icon=":material/upload:", disabled=audio is None):
        response = request(
            "POST",
            f"/meetings/{meeting_id}/upload",
            files={"file": (audio.name, audio.getvalue(), audio.type or "application/octet-stream")},
        )
        if response.is_error:
            st.error(error_text(response))
        else:
            st.rerun()

if detail.get("transcript"):
    with st.expander("Transcript"):
        st.text(detail["transcript"]["raw_text"])

if detail.get("summary"):
    with st.container(border=True):
        st.subheader("Summary", divider="gray")
        st.markdown(detail["summary"]["narrative"])
        structured = detail["summary"]["structured_json"]
        for label, key in (
            ("Decisions", "decisions"),
            ("Key points", "key_points"),
            ("Open questions", "open_questions"),
        ):
            values = structured.get(key) or []
            if values:
                st.markdown(f"**{label}**")
                for value in values:
                    st.markdown(f"- {value}")

has_summary = detail.get("summary") is not None
with st.container(horizontal=True):
    if st.button("Download PDF", icon=":material/picture_as_pdf:", disabled=not has_summary):
        response = request("GET", f"/meetings/{meeting_id}/pdf")
        if response.is_error:
            st.error(error_text(response))
        else:
            st.session_state["pdf_bytes"] = response.content
    if st.button("Send to Discord", icon=":material/send:", disabled=not has_summary):
        response = request("POST", f"/meetings/{meeting_id}/send-discord")
        if response.is_error:
            st.error(error_text(response))
        else:
            st.success("Sent to Discord.")
            st.rerun()

if st.session_state.get("pdf_bytes"):
    st.download_button(
        "Save PDF",
        data=st.session_state["pdf_bytes"],
        file_name=f"{meeting_id}.pdf",
        mime="application/pdf",
        icon=":material/download:",
    )
