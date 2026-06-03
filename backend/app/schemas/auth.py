from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    mfa_required: bool = False
    mfa_token: Optional[str] = None


class TokenPayload(BaseModel):
    sub: str  # user id as string
    role: str
    exp: int


class MeResponse(BaseModel):
    police_user_id: int
    first_name: str
    last_name: str
    email: EmailStr
    phone_number: Optional[str] = None
    badge_number: Optional[str] = None
    rank: str
    role: str
    is_active: bool
    last_login_at: Optional[datetime] = None
    last_password_change: Optional[datetime] = None
    mfa_enabled: bool = False

    class Config:
        from_attributes = True


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=6)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    code: str
    new_password: str = Field(..., min_length=6)


class MfaVerifyRequest(BaseModel):
    mfa_token: str
    code: str

