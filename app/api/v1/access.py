from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
import httpx
from app.core.auth import get_current_user_api
from app.database.access_request_repository import get_access_request_repository, AccessRequestRepository
from app.schemas.access_request import (
    AccessRequestCreateSchema,
    AccessRequestResponseSchema,
    AccessStatusResponseSchema,
    AccessRequestStatus
)
from app.utils.log import logger

router = APIRouter()

DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1488261758002004229/sS_aOnHvsCqRdMMnDhZvCmA0wq8HFl6dgrW0JFS_n17HXUtnIs2wMxR92ZCDxZ910-or"


async def send_discord_notification(user_name: str, user_email: str, platform_url: str, message: str | None):
    """디스코드 웹훅으로 사용 요청 알림 전송"""
    embed = {
        "title": "새로운 오버레이 사용 요청",
        "color": 0x8B5CF6,
        "fields": [
            {"name": "사용자", "value": user_name or "(이름 없음)", "inline": True},
            {"name": "이메일", "value": user_email or "(없음)", "inline": True},
            {"name": "플랫폼 주소", "value": platform_url, "inline": False},
        ],
    }
    if message:
        embed["fields"].append({"name": "메시지", "value": message, "inline": False})

    try:
        async with httpx.AsyncClient() as client:
            await client.post(DISCORD_WEBHOOK_URL, json={"embeds": [embed]}, timeout=10)
    except Exception as e:
        logger.error(f"Discord webhook send failed: {e}")


@router.get("/status", response_model=AccessStatusResponseSchema)
async def get_access_status(
    user=Depends(get_current_user_api),
    repo: AccessRequestRepository = Depends(get_access_request_repository)
):
    """현재 사용자의 오버레이 접근 상태 조회"""
    # 승인 여부 확인
    is_approved = await repo.is_user_approved(user['id'])

    if is_approved:
        return AccessStatusResponseSchema(approved=True)

    # 가장 최근 요청 조회
    latest_request = await repo.get_user_latest_request(user['id'])

    if not latest_request:
        return AccessStatusResponseSchema(approved=False, status=None)

    return AccessStatusResponseSchema(
        approved=False,
        status=AccessRequestStatus(latest_request['status']),
        rejection_reason=latest_request.get('rejection_reason'),
        platform_url=latest_request.get('platform_url'),
        requested_at=latest_request.get('created_at')
    )


@router.post("/request", response_model=AccessRequestResponseSchema)
async def submit_access_request(
    data: AccessRequestCreateSchema,
    background_tasks: BackgroundTasks,
    user=Depends(get_current_user_api),
    repo: AccessRequestRepository = Depends(get_access_request_repository)
):
    """오버레이 접근 요청 제출"""
    # 이미 승인된 경우
    is_approved = await repo.is_user_approved(user['id'])
    if is_approved:
        raise HTTPException(status_code=400, detail="이미 승인된 사용자입니다")

    # 대기 중인 요청이 있는 경우
    pending_request = await repo.get_user_pending_request(user['id'])
    if pending_request:
        raise HTTPException(status_code=400, detail="이미 대기 중인 요청이 있습니다")

    # 요청 생성
    request_id = await repo.create_request(user['id'], data)
    request = await repo.get_request_by_id(request_id)

    # 디스코드 웹훅 알림
    background_tasks.add_task(
        send_discord_notification,
        user.get('name', ''),
        user.get('email', ''),
        data.platform_url,
        data.message,
    )

    return request


@router.get("/my-request", response_model=AccessRequestResponseSchema)
async def get_my_latest_request(
    user=Depends(get_current_user_api),
    repo: AccessRequestRepository = Depends(get_access_request_repository)
):
    """내 가장 최근 요청 조회"""
    request = await repo.get_user_latest_request(user['id'])
    if not request:
        raise HTTPException(status_code=404, detail="요청 내역이 없습니다")
    return request
