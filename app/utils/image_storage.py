"""업로드 이미지(프로필 사진·노래책 커버)의 디스크 저장 위치와 한도.

저장 위치 원칙:
    음원(app/utils/audio_storage.py)과 마찬가지로 app/static 아래에 두지 않는다.
    이 이미지들 자체는 공개 자산이지만(공개 노래책 페이지에 그대로 노출된다),
    StaticFiles 마운트에 얹으면 '무엇이 서빙되는지'를 라우트가 아니라 디렉터리
    내용이 결정하게 된다. 서빙은 라우트 한 곳으로만 나간다
    (프로필: app/api/v1/users.py 의 GET /profile-image/{key},
     노래책 커버: app/api/v1/songbook.py 의 GET /cover-image/{key}).

경로 원칙:
    저장 경로는 uuid4 기반이며 원본 파일명을 쓰지 않는다. DB(users.picture_path,
    streamer_songbooks.cover_image_path)에는 저장 루트 기준 '상대 경로'만 두어,
    루트를 옮겨도 마이그레이션이 필요 없게 한다. 확장자는 서버가 매직바이트로
    판별한 형식에서만 나온다 (app/utils/image_sniff.py).

루트를 나누는 이유:
    프로필 사진은 계정 파기(account_purge)의 대상이고, 노래책 커버는 수록곡과
    함께 사는 자산이라 수명이 다르다. 한 디렉터리에 섞어 두면 '어느 쪽 파일인지'를
    DB 로만 알 수 있어 정리 스크립트가 위험해진다.
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

SONG_COVER_ROOT: Path = (
    Path(settings.song_cover_root).expanduser().resolve()
    if settings.song_cover_root
    else (_REPO_ROOT / "storage" / "cover")
)
SONG_COVER_TMP: Path = SONG_COVER_ROOT / "tmp"

# 파일당 한도. 브라우저가 올리기 전에 정사각형으로 줄여서 보내지만
# (app/static/js/profile_image.js, app/static/js/cover_image.js),
# 서버는 그 전제를 믿지 않는다.
MAX_PROFILE_IMAGE_BYTES = 5 * 1024 * 1024
MAX_SONG_COVER_BYTES = 5 * 1024 * 1024

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


def _resolve_within(root: Path, storage_path: str) -> Path:
    """상대 경로를 실제 파일 경로로 바꾼다 (저장 루트 밖으로 나가면 거부).

    서빙 라우트가 URL 조각을 그대로 넘기는 자리라, 여기가 경로 탈출을 막는
    유일한 지점이다. 읽기/삭제 경로는 모두 이 함수를 거친다.
    """
    candidate = (root / storage_path).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError(f"경로가 저장 루트를 벗어납니다: {storage_path!r}")
    if candidate == root:
        raise ValueError("저장 루트 자체는 파일이 아닙니다.")
    return candidate


def _new_temp_path(tmp_root: Path) -> Path:
    """업로드 중 임시 파일 경로 (.part). 최종 저장 루트와 같은 파일시스템이라
    완료 시 os.replace 가 원자적으로 동작한다."""
    ensure_dir(tmp_root)
    return tmp_root / f"{uuid4().hex}.part"


# 루트별 얇은 진입점. 모듈 전역을 호출 시점에 읽으므로 테스트에서
# PROFILE_IMAGE_ROOT / SONG_COVER_ROOT 를 갈아끼우면 그대로 따라온다.
def resolve_profile_image_path(storage_path: str) -> Path:
    return _resolve_within(PROFILE_IMAGE_ROOT, storage_path)


def new_temp_path() -> Path:
    return _new_temp_path(PROFILE_IMAGE_TMP)


def resolve_song_cover_path(storage_path: str) -> Path:
    return _resolve_within(SONG_COVER_ROOT, storage_path)


def new_cover_temp_path() -> Path:
    return _new_temp_path(SONG_COVER_TMP)
