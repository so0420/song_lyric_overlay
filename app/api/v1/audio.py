"""업로드 음원 API.

재생은 여기에 없다. 음원 재생은 '연결된 가사의 공개 범위'로 판정하므로
`GET /api/v1/lyrics/{lyrics_id}/audio` 가 정식 재생 경로다.
여기의 `GET /{audio_id}` 는 소유자·관리자 전용(연결 전 미리듣기, 노래책 전용 음원)이다.
"""
import hashlib
import os
from typing import Optional

import anyio
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pymysql.err import IntegrityError

from app.core.auth import get_current_user_api
from app.database.audio_repository import AudioRepository, get_audio_repository
from app.utils.audio_sniff import ALLOWED_AUDIO, SNIFF_BYTES, detect_audio_mime
from app.utils.audio_storage import (
    FILE_MODE,
    MAX_AUDIO_BYTES,
    MAX_TOTAL_BYTES_PER_USER,
    ensure_dir,
    new_storage_path,
    new_temp_path,
    resolve_audio_path,
)
from app.utils.csrf import verify_csrf
from app.utils.log import logger
from app.utils.rate_limit import RATE_LIMITS, limiter

router = APIRouter()

# 413 을 돌려줄 때 클라이언트가 응답을 받을 수 있도록 남은 본문을 조금 더 읽어준다.
# (본문을 안 읽고 끊으면 브라우저가 JSON 오류 대신 연결 초기화를 보게 된다)
DRAIN_LIMIT_BYTES = 2 * MAX_AUDIO_BYTES


def _sanitize_filename(name: str) -> Optional[str]:
    """표시 전용 파일명 정리. 경로 조립에는 절대 쓰지 않는다."""
    if not name:
        return None
    cleaned = "".join(ch for ch in name if ch.isprintable() and ch not in '/\\\x00')
    cleaned = cleaned.strip()[:255]
    return cleaned or None


def _serialize(row: dict) -> dict:
    return {
        "id": row["id"],
        "url": f"/api/v1/audio/{row['id']}",
        "mime_type": row["mime_type"],
        "byte_size": row["byte_size"],
        "duration_ms": row.get("duration_ms"),
        "original_filename": row.get("original_filename"),
        "created_at": row.get("created_at"),
    }


async def _drain(request: Request) -> None:
    """오류 응답 전에 남은 요청 본문을 버린다 (상한 있음)."""
    dropped = 0
    try:
        async for chunk in request.stream():
            dropped += len(chunk)
            if dropped > DRAIN_LIMIT_BYTES:
                break
    except Exception:
        pass


@router.post("", dependencies=[Depends(verify_csrf)])
@limiter.limit(RATE_LIMITS["upload_hour"])
@limiter.limit(RATE_LIMITS["upload_minute"])
async def upload_audio(
    request: Request,
    filename: str = Query("", max_length=255, description="원본 파일명 (표시용)"),
    duration_ms: Optional[int] = Query(None, ge=0, le=24 * 60 * 60 * 1000, description="재생 길이 힌트"),
    user=Depends(get_current_user_api),
    repo: AudioRepository = Depends(get_audio_repository),
):
    """가사에 연결할 음원 업로드. **요청 본문 = 파일 바이트 원본** (멀티파트 아님).

    멀티파트를 쓰지 않는 이유:
        FastAPI 는 의존성 해석보다 먼저 본문을 파싱하고(fastapi/routing.py),
        Starlette 의 멀티파트 파서는 파일 파트에 크기 제한을 걸지 않은 채
        임시파일로 흘려보낸다(starlette/formparsers.py 의 max_part_size 는
        비파일 필드에만 적용). 그래서 UploadFile 로는 '읽는 도중 50MB 에서 끊기'가
        불가능하다. 본문 파라미터를 선언하지 않으면 FastAPI 가 본문을 건드리지
        않으므로 request.stream() 을 우리가 직접 제어할 수 있고, 덤으로
        verify_csrf 가 본문을 읽기 전에 돈다.
        => 이 시그니처를 UploadFile 로 '단순화'하지 말 것.
    """
    # 1) 값싼 사전 차단. Content-Length 는 신뢰하지 않지만 맞다면 빨리 끝낼 수 있다.
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="음원 파일은 50MB 를 넘을 수 없습니다.")

    tmp_path = new_temp_path()
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, FILE_MODE)

    head = b""
    total = 0
    hasher = hashlib.sha256()
    oversize = False

    try:
        with os.fdopen(fd, "wb") as f:
            async for chunk in request.stream():
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_AUDIO_BYTES:
                    oversize = True
                    break
                if len(head) < SNIFF_BYTES:
                    head += chunk[: SNIFF_BYTES - len(head)]
                hasher.update(chunk)
                await anyio.to_thread.run_sync(f.write, chunk)
            if not oversize:
                await anyio.to_thread.run_sync(f.flush)
                await anyio.to_thread.run_sync(os.fsync, f.fileno())

        if oversize:
            await _drain(request)
            raise HTTPException(status_code=413, detail="음원 파일은 50MB 를 넘을 수 없습니다.")

        if total == 0:
            raise HTTPException(status_code=400, detail="빈 파일은 업로드할 수 없습니다.")

        # 2) 매직바이트 검사 — 클라이언트가 보낸 Content-Type 은 참고하지 않는다
        mime = detect_audio_mime(head)
        if mime is None:
            raise HTTPException(
                status_code=415,
                detail="지원하지 않는 음원 형식입니다. (mp3, ogg/opus, wav, flac)",
            )

        digest = hasher.hexdigest()

        # 3) 같은 사용자의 동일 파일이면 새로 저장하지 않는다.
        #    (파기 표시된 행도 조회된다 — UNIQUE(owner_id, sha256) 이 deleted_at 을 안 보므로
        #     못 본 척하고 INSERT 하면 중복 키로 500 이 난다)
        existing = await repo.find_by_owner_sha256(user.id, digest)
        if existing and not existing.get("deleted_at"):
            return _serialize(existing)
        revive_id = existing["id"] if existing else None

        # 4) 사용자별 총량 제한 (지금은 꺼져 있음)
        if MAX_TOTAL_BYTES_PER_USER:
            used = await repo.total_bytes(user.id)
            if used + total > MAX_TOTAL_BYTES_PER_USER:
                raise HTTPException(
                    status_code=413,
                    detail="보관 용량을 초과했습니다. 사용하지 않는 음원을 삭제해주세요.",
                )

        # 5) 원자적 배치 — 여기까지 와야 파일이 보이는 위치로 이동한다
        rel_path = new_storage_path(ALLOWED_AUDIO[mime])
        final_path = resolve_audio_path(rel_path)
        ensure_dir(final_path.parent)
        os.replace(tmp_path, final_path)
        os.chmod(final_path, FILE_MODE)
        tmp_path = None  # 아래 finally 에서 지우지 않도록

        display_name = _sanitize_filename(filename)
        try:
            if revive_id is not None:
                # 삭제했던 파일을 다시 올린 경우 — 옛 행을 새 블롭으로 되살린다.
                # (옛 블롭은 리퍼가 이미 지웠을 수 있으므로 경로를 갈아끼운다)
                old_path = existing.get("storage_path")
                await repo.revive(
                    revive_id, storage_path=rel_path, mime_type=mime, byte_size=total,
                    original_filename=display_name, duration_ms=duration_ms,
                )
                audio_id = revive_id
                if old_path and old_path != rel_path:
                    try:
                        resolve_audio_path(old_path).unlink(missing_ok=True)
                    except Exception as e:
                        logger.warning(f"[audio] 옛 블롭 삭제 실패: {old_path} — {e}")
            else:
                audio_id = await repo.create(
                    owner_id=user.id,
                    storage_path=rel_path,
                    mime_type=mime,
                    byte_size=total,
                    sha256=digest,
                    original_filename=display_name,
                    duration_ms=duration_ms,
                )
        except IntegrityError:
            # 같은 파일을 동시에 두 번 올린 경우 (select-then-insert 경쟁).
            # 먼저 들어간 행을 그대로 쓰고, 방금 쓴 블롭은 버린다.
            final_path.unlink(missing_ok=True)
            winner = await repo.find_by_owner_sha256(user.id, digest)
            if winner and not winner.get("deleted_at"):
                return _serialize(winner)
            raise HTTPException(status_code=409, detail="같은 파일을 처리 중입니다. 잠시 후 다시 시도해주세요.")
        except Exception:
            # DB 기록 실패 — 아무도 참조하지 못하는 고아 블롭을 남기지 않는다
            final_path.unlink(missing_ok=True)
            raise

        row = await repo.get_by_id(audio_id)
        logger.info(f"[audio] 업로드 완료 id={audio_id} user={user.id} {mime} {total}B")
        return _serialize(row)
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


@router.get("/my")
@limiter.limit(RATE_LIMITS["api"])
async def list_my_audio(
    request: Request,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user=Depends(get_current_user_api),
    repo: AudioRepository = Depends(get_audio_repository),
):
    """내가 업로드한 음원 목록 (편집기/노래하기의 음원 선택 UI 용)"""
    items = await repo.list_by_owner(user.id, limit=limit, offset=offset)
    total = await repo.count_by_owner(user.id)
    return {
        "items": [_serialize(row) for row in items],
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(items) < total,
    }


@router.get("/{audio_id}")
async def stream_own_audio(
    audio_id: int,
    user=Depends(get_current_user_api),
    repo: AudioRepository = Depends(get_audio_repository),
):
    """소유자(또는 관리자) 전용 재생.

    가사에 연결하기 전 미리듣기와, 노래책 수록곡 전용 음원 재생에 쓴다.
    '이 음원을 참조하는 가사가 하나라도 공개면 허용' 같은 규칙은 쓰지 않는다 —
    다른 가사의 공개 범위가 이 파일의 접근 권한을 좌우하게 되기 때문이다.
    """
    row = await repo.get_by_id(audio_id)
    if not row or row.get("deleted_at"):
        raise HTTPException(status_code=404, detail="음원을 찾을 수 없습니다.")
    if not user.is_admin and row.get("owner_id") != user.id:
        raise HTTPException(status_code=403, detail="이 음원에 접근할 권한이 없습니다.")
    return await build_audio_response(row)


@router.delete("/{audio_id}", dependencies=[Depends(verify_csrf)])
async def delete_audio(
    audio_id: int,
    user=Depends(get_current_user_api),
    repo: AudioRepository = Depends(get_audio_repository),
):
    """음원 삭제 표시. 실제 파일 삭제는 리퍼가 처리한다."""
    row = await repo.get_by_id(audio_id)
    if not row or row.get("deleted_at"):
        raise HTTPException(status_code=404, detail="음원을 찾을 수 없습니다.")
    if row.get("owner_id") != user.id and not user.is_admin:
        raise HTTPException(status_code=404, detail="음원을 찾을 수 없습니다.")

    if await repo.is_linked(audio_id):
        titles = await repo.find_linked_lyrics_titles(audio_id)
        raise HTTPException(
            status_code=409,
            detail={
                "message": "이 음원을 사용 중인 가사가 있어 삭제할 수 없습니다. 먼저 연결을 해제해주세요.",
                "linked_lyrics": titles,
            },
        )

    # 관리자는 소유자가 비어 있는(탈퇴한 사용자의) 음원도 지울 수 있어야 하므로
    # 소유권 조건 없이 삭제 표시한다.
    ok = (
        await repo.claim_for_purge(audio_id)
        if user.is_admin
        else await repo.mark_deleted(audio_id, user.id)
    )
    if not ok:
        raise HTTPException(status_code=404, detail="음원을 찾을 수 없습니다.")
    return {"success": True}


# ---------------------------------------------------------------------
# 공용 헬퍼 — lyrics.py 의 재생 라우트도 이 함수를 쓴다
# ---------------------------------------------------------------------
async def build_audio_response(row: dict) -> FileResponse:
    """audio_files 레코드로 스트리밍 응답을 만든다.

    Range(206)/416/If-Range 는 starlette 의 FileResponse 가 처리한다 —
    <audio> 의 탐색이 여기에 의존하므로 직접 구현하지 않는다.
    주의: filename= 을 넘기면 Content-Disposition 이 attachment 가 되어
    재생 대신 다운로드가 되므로 넘기지 않고 inline 을 명시한다.
    """
    path = resolve_audio_path(row["storage_path"])
    try:
        stat_result = await anyio.to_thread.run_sync(os.stat, path)
    except OSError:
        # DB 행은 있는데 블롭이 없다 = 저장소 드리프트. 500 이 아니라 404 로 내리되 반드시 남긴다.
        logger.error(
            f"[audio] 블롭 누락: audio_id={row['id']} path={row['storage_path']}"
        )
        raise HTTPException(status_code=404, detail="음원 파일을 찾을 수 없습니다.")

    return FileResponse(
        path,
        stat_result=stat_result,
        media_type=row["mime_type"],
        headers={
            "Cache-Control": "private, max-age=3600",
            "Content-Disposition": "inline",
            "X-Content-Type-Options": "nosniff",
        },
    )
