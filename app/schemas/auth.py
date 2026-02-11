from pydantic import BaseModel, EmailStr


class RegisterSchema(BaseModel):
    email: EmailStr
    password: str
    name: str


class VerifyEmailSchema(BaseModel):
    email: EmailStr
    code: str


class LoginSchema(BaseModel):
    email: EmailStr
    password: str


class ResendVerificationSchema(BaseModel):
    email: EmailStr


class ForgotPasswordSchema(BaseModel):
    email: EmailStr


class ResetPasswordSchema(BaseModel):
    email: EmailStr
    code: str
    new_password: str
