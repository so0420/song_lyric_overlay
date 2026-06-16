from fastapi import APIRouter, Depends, HTTPException, Request
from typing import Any, Dict, Optional
import random

from app.core.auth import get_current_user, get_current_user_api
from app.core.overlay_websocket import overlay_manager
from app.core.song_request_push import resolve_mr_video_id, build_push_data
# 공통 승인 게이트 (명세 4절) — streamers 모듈에 정의.
# 본 모듈의 엔드포인트는 명세 표 기준 "로그인+프로필" 패턴이라 현재 직접 사용처는 없음.
from app.api.v1.streamers import require_approved_user  # noqa: F401
from app.database.streamer_repository import get_streamer_repository, StreamerRepository
from app.database.songbook_repository import get_songbook_repository, SongbookRepository
from app.database.song_request_repository import get_song_request_repository, SongRequestRepository
from app.database.song_repository import get_song_repository, SongRepository
from app.schemas.songbook import (
    SongRequestCreateSchema,
    SongRequestUpdateSchema,
    SongRequestReorderSchema,
    MarkDeliveredSchema,
    RandomFillSchema,
    PlaylistRequestCreateSchema,
)
from app.utils.csrf import verify_csrf
from app.utils.rate_limit import limiter, RATE_LIMITS
from app.utils.log import logger

router = APIRouter()

# 스트리머별 대기 중(waiting) 신청 상한 — 익명 신청 폭주 방지
MAX_WAITING_REQUESTS = 100


# ---------------------------------------------------------------
# 공통 헬퍼
# ---------------------------------------------------------------
async def _require_my_streamer(user, streamer_repo: StreamerRepository) -> Dict[str, Any]:
    """본인 스트리머(노래책) 프로필 조회 — 없으면 404"""
    streamer = await streamer_repo.get_by_user_id(user["id"])
    if not streamer:
        raise HTTPException(status_code=404, detail="노래책 프로필이 없습니다.")
    return streamer


# MR 해석 / 푸시 데이터 구성은 공통 모듈을 사용 (치지직 신청과 동일 계약)
_resolve_mr_video_id = resolve_mr_video_id
_build_push_data = build_push_data


# ---------------------------------------------------------------
# 조회
# ---------------------------------------------------------------
@router.get("/")
async def get_song_requests(
    user=Depends(get_current_user_api),
    streamer_repo: StreamerRepository = Depends(get_streamer_repository),
    request_repo: SongRequestRepository = Depends(get_song_request_repository),
):
    """내 신청 목록 조회 (노래책 수록/가사 연결 정보 포함)"""
    streamer = await _require_my_streamer(user, streamer_repo)
    rows = await request_repo.get_requests(streamer["id"])
    for row in rows:
        row["mr_video_id"] = _resolve_mr_video_id(row)
    return {"items": rows}


@router.get("/playlist-pending")
async def get_playlist_pending(
    user=Depends(get_current_user_api),
    streamer_repo: StreamerRepository = Depends(get_streamer_repository),
    request_repo: SongRequestRepository = Depends(get_song_request_repository),
):
    """노래하기 재생목록 자동 추가 미전달분 조회

    프로필이 없거나 자동 추가 옵션이 꺼져 있으면 빈 목록.
    가사/MR 이 없는 임시 신청도 포함한다(영상은 노래하기에서 직접 지정).
    """
    streamer = await streamer_repo.get_by_user_id(user["id"])
    if not streamer or not streamer.get("request_auto_playlist"):
        return {"items": []}

    rows = await request_repo.get_playlist_pending(streamer["id"])
    items = [_build_push_data(row) for row in rows]
    return {"items": items}


# ---------------------------------------------------------------
# 신청 (익명 허용)
# ---------------------------------------------------------------
@router.post("/", dependencies=[Depends(verify_csrf)])
@limiter.limit(RATE_LIMITS["song_request"])
async def create_song_request(
    request: Request,
    data: SongRequestCreateSchema,
    user=Depends(get_current_user),
    streamer_repo: StreamerRepository = Depends(get_streamer_repository),
    song_repo: SongRepository = Depends(get_song_repository),
    request_repo: SongRequestRepository = Depends(get_song_request_repository),
):
    """노래 신청 (익명 허용 — 공개 노래책에서 시청자가 신청)"""
    # 1) 스트리머 공개 조회 (미승인/비활성/탈퇴 시 비노출 = 404)
    streamer = await streamer_repo.get_public_by_external_id(data.streamer_id)
    if not streamer:
        raise HTTPException(status_code=404, detail="스트리머를 찾을 수 없습니다.")

    # 2) 신청 경로 검증
    if data.requester_type == "MANUAL":
        # 수동 추가는 노래책 주인(스트리머 본인)만 가능
        if not user or user.get("id") != streamer["user_id"]:
            raise HTTPException(status_code=403, detail="수동 추가는 노래책 주인만 할 수 있습니다.")
    else:  # WEB
        if not (streamer.get("request_enabled") and streamer.get("request_web_enabled")):
            raise HTTPException(status_code=403, detail="현재 노래 신청을 받지 않고 있습니다.")

    # 3) 곡 정보 검증 (song_id 있으면 존재 확인, song_id/title 둘 다 없으면 400)
    if data.song_id is not None:
        song = await song_repo.get_song_with_artist(song_id=data.song_id)
        if not song:
            raise HTTPException(status_code=400, detail="노래를 찾을 수 없습니다.")
    elif not data.title:
        raise HTTPException(status_code=400, detail="신청할 곡 정보(song_id 또는 title)가 필요합니다.")

    # 4) 웹 신청은 동일 신청자의 대기 중(waiting) 중복 차단 + 스트리머별 대기 상한
    if data.requester_type == "WEB":
        is_duplicate = await request_repo.has_waiting_duplicate(
            streamer["id"], data.requester, song_id=data.song_id, title=data.title
        )
        if is_duplicate:
            raise HTTPException(status_code=400, detail="이미 대기 중인 동일한 신청이 있습니다.")
        # 닉네임을 바꿔가며 무한 신청하는 폭주를 막기 위한 대기 건수 상한
        if await request_repo.count_waiting(streamer["id"]) >= MAX_WAITING_REQUESTS:
            raise HTTPException(status_code=400, detail="대기 중인 신청이 너무 많습니다. 잠시 후 다시 시도해주세요.")

    # 5) 신청 등록
    request_id = await request_repo.add_request(
        streamer_id=streamer["id"],
        requester=data.requester,
        requester_type=data.requester_type,
        requester_platform="Web",
        song_id=data.song_id,
        title=data.title,
        artist=data.artist,
    )

    # 6) 노래하기 페이지로 WS 푸시 (실패해도 신청 자체는 성공 처리)
    try:
        row = await request_repo.get_request_push_data(request_id)
        if row:
            await overlay_manager.broadcast_to_singers(streamer["user_id"], {
                "type": "song_request_new",
                "data": _build_push_data(row, auto_playlist=bool(streamer.get("request_auto_playlist"))),
            })
    except Exception as e:
        logger.warning(f"노래 신청 WS 푸시 실패 (request_id={request_id}): {e}")

    return {"success": True, "request_id": request_id}


# ---------------------------------------------------------------
# 일괄 작업 (스트리머 본인 관리)
# ---------------------------------------------------------------
@router.post("/batch/random", dependencies=[Depends(verify_csrf)])
async def fill_random_requests(
    data: RandomFillSchema,
    user=Depends(get_current_user_api),
    streamer_repo: StreamerRepository = Depends(get_streamer_repository),
    songbook_repo: SongbookRepository = Depends(get_songbook_repository),
    request_repo: SongRequestRepository = Depends(get_song_request_repository),
):
    """본인 노래책에서 무작위로 골라 신청 목록 채우기 (부족하면 전부)

    WS 푸시 없음. delivered_at 은 NULL 유지 — 노래하기 페이지 재생목록 합류 대상.
    """
    streamer = await _require_my_streamer(user, streamer_repo)

    entries = await songbook_repo.get_songbook(streamer["id"])
    if not entries:
        return {"success": True, "added": 0}

    sampled = random.sample(entries, min(data.n, len(entries)))
    added = 0
    for entry in sampled:
        await request_repo.add_request(
            streamer_id=streamer["id"],
            requester="시스템 랜덤",
            requester_type="MANUAL",
            requester_platform="Web",
            song_id=entry["song_id"],
        )
        added += 1

    return {"success": True, "added": added}


@router.delete("/batch/done", dependencies=[Depends(verify_csrf)])
async def delete_done_requests(
    user=Depends(get_current_user_api),
    streamer_repo: StreamerRepository = Depends(get_streamer_repository),
    request_repo: SongRequestRepository = Depends(get_song_request_repository),
):
    """이미 부른(done) 신청 일괄 삭제"""
    streamer = await _require_my_streamer(user, streamer_repo)
    deleted = await request_repo.delete_done(streamer["id"])
    return {"success": True, "deleted": deleted}


@router.delete("/batch/all", dependencies=[Depends(verify_csrf)])
async def delete_all_requests(
    user=Depends(get_current_user_api),
    streamer_repo: StreamerRepository = Depends(get_streamer_repository),
    request_repo: SongRequestRepository = Depends(get_song_request_repository),
):
    """신청 전체 삭제"""
    streamer = await _require_my_streamer(user, streamer_repo)
    deleted = await request_repo.delete_all(streamer["id"])
    return {"success": True, "deleted": deleted}


# ---------------------------------------------------------------
# 정렬 / 상태머신 (스트리머 본인 관리)
# ---------------------------------------------------------------
@router.put("/reorder", dependencies=[Depends(verify_csrf)])
async def reorder_requests(
    data: SongRequestReorderSchema,
    user=Depends(get_current_user_api),
    streamer_repo: StreamerRepository = Depends(get_streamer_repository),
    request_repo: SongRequestRepository = Depends(get_song_request_repository),
):
    """신청 순서 재정렬 (전달된 ID 순서대로, 트랜잭션)"""
    streamer = await _require_my_streamer(user, streamer_repo)
    await request_repo.reorder(streamer["id"], data.ids)
    return {"success": True}


@router.post("/next", dependencies=[Depends(verify_csrf)])
async def next_request(
    user=Depends(get_current_user_api),
    streamer_repo: StreamerRepository = Depends(get_streamer_repository),
    request_repo: SongRequestRepository = Depends(get_song_request_repository),
):
    """다음 곡: 부르는 중 → 이미 부름, 첫 대기 곡 → 부르는 중"""
    streamer = await _require_my_streamer(user, streamer_repo)
    next_id = await request_repo.next_request(streamer["id"])
    return {"success": True, "next_id": next_id}


@router.post("/prev", dependencies=[Depends(verify_csrf)])
async def prev_request(
    user=Depends(get_current_user_api),
    streamer_repo: StreamerRepository = Depends(get_streamer_repository),
    request_repo: SongRequestRepository = Depends(get_song_request_repository),
):
    """이전 곡: 부르는 중 → 대기, 마지막 부른 곡 → 부르는 중"""
    streamer = await _require_my_streamer(user, streamer_repo)
    prev_id = await request_repo.prev_request(streamer["id"])
    return {"success": True, "prev_id": prev_id}


@router.post("/reset-status", dependencies=[Depends(verify_csrf)])
async def reset_request_status(
    user=Depends(get_current_user_api),
    streamer_repo: StreamerRepository = Depends(get_streamer_repository),
    request_repo: SongRequestRepository = Depends(get_song_request_repository),
):
    """전체 상태 초기화 (모두 대기중 — delivered_at 은 유지해 재생목록 재전달 방지)"""
    streamer = await _require_my_streamer(user, streamer_repo)
    await request_repo.reset_status(streamer["id"])
    return {"success": True}


@router.post("/mark-delivered", dependencies=[Depends(verify_csrf)])
async def mark_requests_delivered(
    data: MarkDeliveredSchema,
    user=Depends(get_current_user_api),
    streamer_repo: StreamerRepository = Depends(get_streamer_repository),
    request_repo: SongRequestRepository = Depends(get_song_request_repository),
):
    """노래하기 재생목록 전달 완료 마킹 (delivered_at = NOW())"""
    streamer = await _require_my_streamer(user, streamer_repo)
    await request_repo.mark_delivered(streamer["id"], data.ids)
    return {"success": True}


@router.post("/from-playlist", dependencies=[Depends(verify_csrf)])
async def create_request_from_playlist(
    data: PlaylistRequestCreateSchema,
    user=Depends(get_current_user_api),
    streamer_repo: StreamerRepository = Depends(get_streamer_repository),
    request_repo: SongRequestRepository = Depends(get_song_request_repository),
    song_repo: SongRepository = Depends(get_song_repository),
):
    """노래하기 재생목록에서 직접 추가한 곡을 신청목록에도 생성 (재생목록→신청목록 동기화)

    WS 푸시 없이 곧바로 delivered 처리 → 재생목록으로 되돌아오지 않음(이중 추가/루프 차단).
    프로필이 없으면 404 (호출 측은 조용히 무시).
    """
    streamer = await _require_my_streamer(user, streamer_repo)
    if not data.title and not data.song_external_id:
        raise HTTPException(status_code=400, detail="곡 정보가 필요합니다.")

    internal_song_id = None
    if data.song_external_id:
        song = await song_repo.get_song_by_external_id(data.song_external_id)
        internal_song_id = song["id"] if song else None

    request_id = await request_repo.add_request(
        streamer_id=streamer["id"],
        requester="직접 추가",
        requester_type="MANUAL",
        requester_platform="Playlist",
        song_id=internal_song_id,
        title=data.title,
        artist=data.artist,
    )
    # 재생목록發이므로 전달 완료 처리 (playlist-pending 재수집 대상에서 제외)
    await request_repo.mark_delivered(streamer["id"], [request_id])
    return {"request_id": request_id}


# ---------------------------------------------------------------
# 개별 수정 / 삭제 (스트리머 본인 관리) — 동적 경로는 마지막에 정의
# ---------------------------------------------------------------
@router.patch("/{request_id}", dependencies=[Depends(verify_csrf)])
async def update_song_request(
    request_id: int,
    data: SongRequestUpdateSchema,
    user=Depends(get_current_user_api),
    streamer_repo: StreamerRepository = Depends(get_streamer_repository),
    request_repo: SongRequestRepository = Depends(get_song_request_repository),
):
    """신청 수정 (상태/순서/제목/아티스트 — 소유권은 WHERE streamer_id 로 검증)"""
    streamer = await _require_my_streamer(user, streamer_repo)
    fields = data.model_dump(exclude_unset=True)
    # 존재/소유권은 별도 확인 — 동일 값(no-op) 수정은 변경 행이 0이라 404로 오인되면 안 됨
    if not await request_repo.belongs_to(request_id, streamer["id"]):
        raise HTTPException(status_code=404, detail="신청을 찾을 수 없습니다.")
    if fields:
        await request_repo.update_request(request_id, streamer["id"], **fields)
    return {"success": True}


@router.delete("/{request_id}", dependencies=[Depends(verify_csrf)])
async def delete_song_request(
    request_id: int,
    user=Depends(get_current_user_api),
    streamer_repo: StreamerRepository = Depends(get_streamer_repository),
    request_repo: SongRequestRepository = Depends(get_song_request_repository),
):
    """신청 개별 삭제 (소유권은 WHERE streamer_id 로 검증)"""
    streamer = await _require_my_streamer(user, streamer_repo)
    affected = await request_repo.delete_request(request_id, streamer["id"])
    if affected == 0:
        raise HTTPException(status_code=404, detail="신청을 찾을 수 없습니다.")
    return {"success": True}
