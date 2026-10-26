"""Live capture request and response models."""

from datetime import datetime

from pydantic import BaseModel


class LiveTicketOut(BaseModel):
    ticket: str
    ws_url: str
    expires_at: datetime
