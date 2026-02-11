from .pagination import PaginationParams, PaginatedResponse
from .common import SuccessResponse
from .auth import (
    RegisterSchema,
    VerifyEmailSchema,
    LoginSchema,
    ResendVerificationSchema,
    ForgotPasswordSchema,
    ResetPasswordSchema
)
from .users import ProfileUpdateSchema, PasswordChangeSchema, EmailOtpSchema
from .lyrics import LyricsCreateSchema, LyricsUpdateSchema
from .overlay import OverlaySettingsSchema
