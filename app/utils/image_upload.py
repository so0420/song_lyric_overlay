"""요청 본문(이미지 바이트 원본)을 받아 디스크에 안전하게 내려놓는 공통 절차.

프로필 사진(app/api/v1/users.py)과 노래책 커버(app/api/v1/songbook.py)가 같은
절차를 쓴다. 보안에 민감한 부분(한도 초과 시 읽는 도중 중단, 매직바이트 판별,
원자적 배치)을 두 벌로 두면 한쪽만 고쳐지는 사고가 나므로 한 곳에 모았다.

**요청 본문 = 이미지 바이트 원본** (멀티파트 아님).
멀티파트를 쓰지 않는 이유는 app/api/v1/audio.py 의 upload_audio 와 같다:
본문 파라미터를 선언하지 않아야 FastAPI 가 본문을 건드리지 않고, 그래야
'읽는 도중 한도에서 끊기'와 '본문을 읽기 전에 verify_csrf 실행'이 둘 다 된다.
=> 호출부 시그니처를 UploadFile 로 '단순화'하지 말 것.
"""
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import anyio
from fastapi import HTTPException, Request

from app.utils.image_sniff import ALLOWED_IMAGE, SNIFF_BYTES, detect_image_mime
from app.utils.image_storage import FILE_MODE, ensure_dir, new_storage_path
from app.utils.log import logger


@dataclass(frozen=True)
class StoredImage:
    """디스크에 배치까지 끝난 업로드 이미지"""
    storage_path: str   # 저장 루트 기준 상대 경로
    path: Path          # 실제 파일 경로
    mime: str           # 서버가 매직바이트로 판별한 형식
    byte_size: int


async def _drain(request: Request, limit: int) -> None:
    """오류 응답 전에 남은 요청 본문을 버린다 (상한 있음).

    본문을 안 읽고 끊으면 브라우저가 JSON 오류 대신 연결 초기화를 보게 된다.
    """
    dropped = 0
    try:
        async for chunk in request.stream():
            dropped += len(chunk)
            if dropped > limit:
                break
    except Exception:
        pass


async def receive_image(
    request: Request,
    *,
    max_bytes: int,
    temp_factory: Callable[[], Path],
    resolver: Callable[[str], Path],
    oversize_detail: str,
) -> StoredImage:
    """본문을 스트리밍으로 받아 검증하고 최종 위치에 원자적으로 배치한다.

    Args:
        max_bytes: 파일당 한도. 넘으면 읽기를 중단하고 413.
        temp_factory: 임시 .part 경로 생성기 (최종 루트와 같은 파일시스템이어야 한다)
        resolver: 상대 경로 -> 실제 경로 (저장 루트 밖이면 ValueError)
        oversize_detail: 413 응답 메시지

    Raises:
        HTTPException: 413(크기 초과) / 400(빈 파일) / 415(허용하지 않는 형식)
    """
    # 1) 값싼 사전 차단. Content-Length 는 신뢰하지 않지만 맞다면 빨리 끝낼 수 있다.
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > max_bytes:
        raise HTTPException(status_code=413, detail=oversize_detail)

    tmp_path = temp_factory()
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, FILE_MODE)

    head = b""
    total = 0
    oversize = False

    try:
        with os.fdopen(fd, "wb") as f:
            async for chunk in request.stream():
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    oversize = True
                    break
                if len(head) < SNIFF_BYTES:
                    head += chunk[: SNIFF_BYTES - len(head)]
                await anyio.to_thread.run_sync(f.write, chunk)
            if not oversize:
                await anyio.to_thread.run_sync(f.flush)
                await anyio.to_thread.run_sync(os.fsync, f.fileno())

        if oversize:
            await _drain(request, 2 * max_bytes)
            raise HTTPException(status_code=413, detail=oversize_detail)

        if total == 0:
            raise HTTPException(status_code=400, detail="빈 파일은 업로드할 수 없습니다.")

        # 2) 매직바이트 검사 — 클라이언트가 보낸 Content-Type 은 참고하지 않는다
        mime = detect_image_mime(head)
        if mime is None:
            raise HTTPException(
                status_code=415,
                detail="지원하지 않는 이미지 형식입니다. (jpg, png, webp, gif)",
            )

        # 3) 원자적 배치 — 여기까지 와야 파일이 보이는 위치로 이동한다
        rel_path = new_storage_path(ALLOWED_IMAGE[mime])
        final_path = resolver(rel_path)
        ensure_dir(final_path.parent)
        os.replace(tmp_path, final_path)
        os.chmod(final_path, FILE_MODE)
        tmp_path = None  # 아래 finally 에서 지우지 않도록

        return StoredImage(storage_path=rel_path, path=final_path, mime=mime, byte_size=total)
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


async def unlink_image(storage_path: str | None, resolver: Callable[[str], Path], label: str) -> None:
    """옛 이미지 파일을 지운다. 실패해도 요청을 실패시키지는 않는다."""
    if not storage_path:
        return
    try:
        path = resolver(storage_path)
        await anyio.to_thread.run_sync(lambda: path.unlink(missing_ok=True))
    except Exception as e:
        logger.warning(f"[{label}] 옛 이미지 삭제 실패: {storage_path} — {e}")
