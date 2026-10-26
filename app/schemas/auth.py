"""Authentication request and response models."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=255)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: EmailStr
    name: str


class AuthResponse(BaseModel):
    token: str
    expires_at: datetime
    user: UserOut


class AuthConfigOut(BaseModel):
    email: bool = True
    google: bool = False
    required: bool = True
