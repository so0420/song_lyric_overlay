"""업로드 음원의 디스크 저장 위치와 한도.

저장 위치 원칙:
    절대로 app/static 아래에 두지 않는다. song_lyric.py 의 StaticFiles 마운트가
    인증 없이 공개해 버리기 때문이다. 재생은 반드시 권한 검사를 거치는
    라우트(app/api/v1/lyrics.py 의 /{lyrics_id}/audio)를 통해서만 이뤄진다.

경로 원칙:
    저장 경로는 uuid4 기반이며 원본 파일명을 쓰지 않는다. DB 에는 저장 루트 기준
    '상대 경로'만 두어, 루트를 옮겨도 데이터 마이그레이션이 필요 없게 한다.
    확장자는 서버가 매직바이트로 판별한 형식에서만 나온다 (app/utils/audio_sniff.py).
"""
import os
from pathlib import Path
from uuid import uuid4

from app.utils.config import settings

# app/utils/audio_storage.py -> parents[2] == 리포지토리 루트
# (song_lyric.py 의 StaticFiles(directory="app/static") 처럼 cwd 에 의존하지 않게 한다)
_REPO_ROOT = Path(__file__).resolve().parents[2]

AUDIO_ROOT: Path = (
    Path(settings.audio_storage_root).expanduser().resolve()
    if settings.audio_storage_root
    else (_REPO_ROOT / "storage" / "audio")
)
AUDIO_TMP: Path = AUDIO_ROOT / "tmp"

# 파일당 한도. 사용자당 총량 한도는 현재 없음(0), 필요해지면 여기만 켜면 된다.
MAX_AUDIO_BYTES = 50 * 1024 * 1024
MAX_TOTAL_BYTES_PER_USER = 0  # 0 = 무제한

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
    """새 저장 상대 경로를 만든다. 예: 'ab/cd/abcd....mp3'

    앞 4자리로 2단계 팬아웃(65536 버킷)해서 한 디렉터리가 커지지 않게 한다.
    """
    key = uuid4().hex
    return f"{key[0:2]}/{key[2:4]}/{key}.{extension}"


def resolve_audio_path(storage_path: str) -> Path:
    """상대 경로를 실제 파일 경로로 바꾼다 (저장 루트 밖으로 나가면 거부).

    storage_path 는 우리가 만든 값만 들어오지만, 경로 결합은 조용히 틀리기 쉬운
    지점이라 모든 읽기/삭제 경로가 이 함수를 거치게 한다.
    """
    candidate = (AUDIO_ROOT / storage_path).resolve()
    if not candidate.is_relative_to(AUDIO_ROOT):
        raise ValueError(f"경로가 저장 루트를 벗어납니다: {storage_path!r}")
    return candidate


def new_temp_path() -> Path:
    """업로드 중 임시 파일 경로 (.part). AUDIO_ROOT 와 같은 파일시스템이라
    완료 시 os.replace 가 원자적으로 동작한다."""
    ensure_dir(AUDIO_TMP)
    return AUDIO_TMP / f"{uuid4().hex}.part"
