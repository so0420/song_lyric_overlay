from pydantic import BaseModel, Field, AliasPath


class Chat(BaseModel):
    streamer_uid: str = Field(validation_alias=AliasPath('channelId'), description="스트리머 uid")
    streamer_name: str = Field(default="Unknown", validation_alias=AliasPath('channelName'), description="스트리머 이름")
    user_uid: str = Field(validation_alias=AliasPath('data', 'senderChannelId'), description="유저 uid")
    user_name: str = Field(default="익명", validation_alias=AliasPath('data', 'profile', 'nickname'), description="유저 닉네임")
    user_message: str = Field(validation_alias=AliasPath('data', 'content'), description="유저 메시지")
    user_role: str = Field(default="user", validation_alias=AliasPath('data', 'profile', 'userRoleCode'), description="유저 역할")
    badges: list = Field(default=[], validation_alias=AliasPath('data', 'profile', 'badges'), description="유저 뱃지")
    profile: dict | None = Field(default=None, validation_alias=AliasPath('data', 'profile'), description="유저 프로필")
    emojis: dict | None = Field(default=None, validation_alias=AliasPath('data', 'emojis'), description="이모지")
    message_time: int = Field(validation_alias=AliasPath('data', 'messageTime'), description="메시지 시간")
    event_sent_at: str | None = Field(default=None, validation_alias=AliasPath('data', 'eventSentAt'), description="이벤트 발생 시간")


class Donation(BaseModel):
    streamer_uid: str = Field(validation_alias=AliasPath('channelId'), description="스트리머 uid")
    streamer_name: str = Field(default="Unknown", validation_alias=AliasPath('channelName'), description="스트리머 이름")
    user_uid: str | None = Field(default="anonymous", validation_alias=AliasPath('data', 'donatorChannelId'), description="유저 uid")
    user_name: str = Field(default="", validation_alias=AliasPath('data', 'donatorNickname'), description="유저 닉네임")
    user_message: str = Field(default="", validation_alias=AliasPath('data', 'donationText'), description="유저 메시지")
    donation_type: str = Field(validation_alias=AliasPath('data', 'donationType'), description="후원 타입")
    pay_amount: int = Field(validation_alias=AliasPath('data', 'payAmount'), description="후원 금액")
    emojis: dict | None = Field(default=None, validation_alias=AliasPath('data', 'emojis'), description="이모지")
    event_sent_at: str | None = Field(default=None, validation_alias=AliasPath('data', 'eventSentAt'), description="이벤트 발생 시간")


class Subscription(BaseModel):
    streamer_uid: str = Field(validation_alias=AliasPath('channelId'), description="스트리머 uid")
    streamer_name: str = Field(default="Unknown", validation_alias=AliasPath('channelName'), description="스트리머 이름")
    user_uid: str = Field(validation_alias=AliasPath('data', 'subscriberChannelId'), description="유저 uid")
    user_name: str = Field(default="익명", validation_alias=AliasPath('data', 'subscriberNickname'), description="유저 닉네임")
    tier_no: int | None = Field(default=None, validation_alias=AliasPath('data', 'tierNo'), description="구독 티어")
    tier_name: str | None = Field(default=None, validation_alias=AliasPath('data', 'tierName'), description="구독 티어 이름")
    month: int = Field(validation_alias=AliasPath('data', 'month'), description="구독 개월 수")

