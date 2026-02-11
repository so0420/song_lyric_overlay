from pydantic import BaseModel
from typing import Optional


class CurrentUserSchema(BaseModel):
    id: int
    email: str
    name: str
    is_admin: bool = False

    def __getitem__(self, key: str):
        """dict-like access for backward compatibility"""
        return getattr(self, key)

    def get(self, key: str, default=None):
        """dict-like get for backward compatibility"""
        return getattr(self, key, default)


class ProfileUpdateSchema(BaseModel):
    name: str
    email: str
    otp_code: Optional[str] = None


class PasswordChangeSchema(BaseModel):
    current_password: Optional[str] = None
    new_password: str


class EmailOtpSchema(BaseModel):
    email: str
