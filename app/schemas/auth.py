from pydantic import BaseModel, EmailStr


class RegisterSchema(BaseModel):
    email: EmailStr
    password: str
    name: str
    # 탈퇴한 계정의 이메일로 가입을 시도할 때만 쓰인다.
    #   None  — 아직 묻지 않음. 서버가 409 로 '복구할지' 되묻는다.
    #   True  — 이전 계정을 복구한다 (가사·노래책 등이 그대로 남는다)
    #   False — 이전 계정은 버리고 새 계정으로 시작한다
    restore: bool | None = None


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
