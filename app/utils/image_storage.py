"""업로드 프로필 사진의 디스크 저장 위치와 한도.

저장 위치 원칙:
    음원(app/utils/audio_storage.py)과 마찬가지로 app/static 아래에 두지 않는다.
    프로필 사진 자체는 공개 자산이지만(공개 노래책 페이지에 그대로 노출된다),
    StaticFiles 마운트에 얹으면 '무엇이 서빙되는지'를 라우트가 아니라 디렉터리
    내용이 결정하게 된다. 서빙은 app/api/v1/users.py 의
    GET /profile-image/{key} 한 곳으로만 나간다.

경로 원칙:
    저장 경로는 uuid4 기반이며 원본 파일명을 쓰지 않는다. DB(users.picture_path)
    에는 저장 루트 기준 '상대 경로'만 두어, 루트를 옮겨도 마이그레이션이
    필요 없게 한다. 확장자는 서버가 매직바이트로 판별한 형식에서만 나온다
    (app/utils/image_sniff.py).
"""
import os
from pathlib import Path
from uuid import uuid4

from app.utils.config import settings

# app/utils/image_storage.py -> parents[2] == 리포지토리 루트
_REPO_ROOT = Path(__file__).resolve().parents[2]

PROFILE_IMAGE_ROOT: Path = (
    Path(settings.profile_image_root).expanduser().resolve()
    if settings.profile_image_root
    else (_REPO_ROOT / "storage" / "profile")
)
PROFILE_IMAGE_TMP: Path = PROFILE_IMAGE_ROOT / "tmp"

# 파일당 한도. 브라우저가 올리기 전에 512px 정사각형으로 줄여서 보내지만
# (app/static/js/profile_image.js), 서버는 그 전제를 믿지 않는다.
MAX_PROFILE_IMAGE_BYTES = 5 * 1024 * 1024

DIR_MODE = 0o750
FILE_MODE = 0o640


def ensure_dir(path: Path) -> None:
    """디렉터리 생성 (권한은 umask 영향을 받으므로 생성 후 다시 지정)"""
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, DIR_MODE)
    except OSError:
        pass  # 이미 다른 권한으로 존재하는 경우 — 치명적이지 않다


def new_storage_path(extension: str) -> str:
    """새 저장 상대 경로를 만든다. 예: 'ab/cd/abcd....jpg'

    앞 4자리로 2단계 팬아웃(65536 버킷)해서 한 디렉터리가 커지지 않게 한다.
    """
    key = uuid4().hex
    return f"{key[0:2]}/{key[2:4]}/{key}.{extension}"


def resolve_profile_image_path(storage_path: str) -> Path:
    """상대 경로를 실제 파일 경로로 바꾼다 (저장 루트 밖으로 나가면 거부).

    서빙 라우트가 URL 조각을 그대로 넘기는 자리라, 여기가 경로 탈출을 막는
    유일한 지점이다. 읽기/삭제 경로는 모두 이 함수를 거친다.
    """
    candidate = (PROFILE_IMAGE_ROOT / storage_path).resolve()
    if not candidate.is_relative_to(PROFILE_IMAGE_ROOT):
        raise ValueError(f"경로가 저장 루트를 벗어납니다: {storage_path!r}")
    if candidate == PROFILE_IMAGE_ROOT:
        raise ValueError("저장 루트 자체는 파일이 아닙니다.")
    return candidate


def new_temp_path() -> Path:
    """업로드 중 임시 파일 경로 (.part). PROFILE_IMAGE_ROOT 와 같은 파일시스템이라
    완료 시 os.replace 가 원자적으로 동작한다."""
    ensure_dir(PROFILE_IMAGE_TMP)
    return PROFILE_IMAGE_TMP / f"{uuid4().hex}.part"
