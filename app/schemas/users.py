from pydantic import BaseModel
from typing import Optional


class ProfileUpdateSchema(BaseModel):
    name: str
    email: str
    otp_code: Optional[str] = None


class PasswordChangeSchema(BaseModel):
    current_password: Optional[str] = None
    new_password: str


class EmailOtpSchema(BaseModel):
    email: str
