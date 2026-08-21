"""탈퇴 계정의 개인정보 자동 파기.

탈퇴는 소프트 삭제(users.deleted_at)만 하므로 식별정보가 계속 남는다.
탈퇴 후 RETENTION_DAYS 가 지나면 식별정보만 지우고 users 행 자체는 남긴다.
행을 남기는 이유는 가사·노래책 등이 owner_id 로 이 행을 참조하고 있어서,
행을 지우면 연결된 데이터가 함께 사라지거나 깨지기 때문이다.

지우는 항목 (개인정보 처리방침의 파기 조항과 같아야 한다):
    users 행에서 비우는 값
        이메일, 이름, 비밀번호 해시, 프로필 사진(디스크의 파일과 URL),
        최근 로그인 IP, 최근 로그인 일시, 오버레이 토큰
    통째로 지우는 행
        소셜 계정 연결, 가사 즐겨찾기, 가사별 개인 메모, 재생목록,
        오버레이 설정·프리셋, 노래 타임라인 기록, 치지직 채널 연동,
        노래책 프로필(수록곡·노래 신청 내역·신청 통계가 CASCADE 로 함께 삭제된다),
        업로드한 음원 파일 (디스크의 파일과 audio_files 기록)

남기는 항목:
    users.id, 가입 일시, 탈퇴 일시, 파기 일시, 관리자/승인 플래그
    → 통계와 연결 무결성을 위해 필요하고, 개인을 식별하지 않는다.
    이용자가 작성한 가사(songs, song_lyrics)
    → 다른 이용자가 이미 사용 중일 수 있어 함께 지우지 않는다.
      다만 그 가사에 연결돼 있던 업로드 음원은 위와 같이 파기되므로,
      가사는 남아도 음원은 재생되지 않는다.
"""
import anyio

from app.database.mariadb import db_handler
from app.utils import audio_storage, image_storage
from app.utils.log import logger

# 탈퇴 후 이 기간이 지나면 파기한다
RETENTION_DAYS = 30

# 한 번에 처리할 최대 계정 수. 실수나 버그가 있어도 한 번에 전부 날아가지 않도록 하는 안전장치.
BATCH_LIMIT = 200

_PURGE_TARGET_SQL = """
    SELECT id
      FROM users
     WHERE deleted_at IS NOT NULL
       AND purged_at IS NULL
       AND deleted_at < (NOW() - INTERVAL %s DAY)
     ORDER BY deleted_at
     LIMIT %s
"""

# 사용자별 데이터를 담고 있어 행째로 지우는 테이블.
# streamers 를 지우면 streamer_songbooks·song_requests·song_request_logs 가
# ON DELETE CASCADE 로 함께 지워진다(노래책 프로필·수록곡·신청 내역·신청 통계).
# audio_files 는 여기 넣지 않는다 — 행을 지우기 전에 storage_path 를 확보해야
# 디스크 파일을 지울 수 있고, 파일 I/O 를 트랜잭션 안에서 하면 안 되기 때문이다.
# (purge_account 에서 별도로 처리한다)
_PURGE_TABLES = (
    ("social_accounts", "user_id"),            # 소셜 계정 연결 정보
    ("user_lyrics_favorites", "user_id"),      # 가사 즐겨찾기
    ("user_lyrics_memos", "user_id"),          # 가사별 개인 메모
    ("user_playlists", "user_id"),             # 재생목록
    ("user_overlay_settings", "user_id"),      # 오버레이 설정
    ("user_overlay_presets", "user_id"),       # 오버레이 프리셋
    ("singing_timeline_records", "user_id"),   # 노래 타임라인 기록
    ("user_chzzk_channels", "user_id"),        # 치지직 채널 연동 정보
    ("streamers", "user_id"),                  # 노래책 프로필 (하위는 CASCADE)
)

_PURGE_USER_SQL = """
    UPDATE users
       SET email = NULL,
           name = NULL,
           password_hash = NULL,
           picture = NULL,
           picture_path = NULL,
           ip = NULL,
           last_login = NULL,
           overlay_token = NULL,
           email_verified = 0,
           purged_at = NOW()
     WHERE id = %s
       AND deleted_at IS NOT NULL
       AND purged_at IS NULL
"""


async def find_purge_targets(retention_days: int = RETENTION_DAYS, limit: int = BATCH_LIMIT) -> list[int]:
    """파기 대상 계정 ID 목록. 실제로 지우지 않으므로 점검용으로도 쓸 수 있다."""
    rows = await db_handler.fetch_all(_PURGE_TARGET_SQL, (retention_days, limit))
    return [r["id"] for r in rows]


async def purge_account(user_id: int) -> bool:
    """계정 하나의 식별정보를 파기한다. 실제로 파기했으면 True.

    탈퇴하지 않았거나 이미 파기된 계정은 아무것도 건드리지 않는다.
    (TransactionContext.execute_query 는 rowcount 가 아니라 lastrowid 를 돌려주므로
     반영 여부는 반환값이 아니라 사전 확인으로 판단한다)
    """
    async with db_handler.transaction() as tx:
        target = await tx.fetch_one(
            "SELECT id FROM users WHERE id = %s AND deleted_at IS NOT NULL AND purged_at IS NULL FOR UPDATE",
            (user_id,),
        )
        if not target:
            return False

        # 업로드 음원: 행을 지우기 전에 파일 경로를 확보한다 (행이 사라지면 경로를 알 수 없다).
        # 행 삭제로 song_lyrics.audio_file_id / streamer_songbooks.audio_file_id 는
        # FK 의 ON DELETE SET NULL 로 정리된다.
        audio_rows = await tx.fetch_all(
            "SELECT storage_path FROM audio_files WHERE owner_id = %s", (user_id,)
        )

        # 프로필 사진도 같은 이유로 경로를 미리 확보한다 (아래 _PURGE_USER_SQL 이 컬럼을 비운다)
        picture_row = await tx.fetch_one(
            "SELECT picture_path FROM users WHERE id = %s", (user_id,)
        )
        picture_path = picture_row.get("picture_path") if picture_row else None
        await tx.execute_query("DELETE FROM audio_files WHERE owner_id = %s", (user_id,))

        for table, column in _PURGE_TABLES:
            await tx.execute_query(f"DELETE FROM {table} WHERE {column} = %s", (user_id,))
        await tx.execute_query(_PURGE_USER_SQL, (user_id,))

    # 커밋된 뒤에 디스크 파일을 지운다. 여기서 실패해도 DB 는 이미 정리됐고,
    # 남은 파일은 purge_audio.py --verify 가 잡아낸다.
    for row in audio_rows:
        try:
            path = audio_storage.resolve_audio_path(row["storage_path"])
            await anyio.to_thread.run_sync(lambda p=path: p.unlink(missing_ok=True))
        except Exception as e:
            logger.error(f"[account_purge] 음원 파일 삭제 실패: {row['storage_path']} — {e}")

    if picture_path:
        try:
            path = image_storage.resolve_profile_image_path(picture_path)
            await anyio.to_thread.run_sync(lambda p=path: p.unlink(missing_ok=True))
        except Exception as e:
            logger.error(f"[account_purge] 프로필 사진 삭제 실패: {picture_path} — {e}")

    logger.info(f"[account_purge] 계정 {user_id} 개인정보 파기 완료 (음원 {len(audio_rows)}건 포함)")
    return True


async def purge_expired_accounts(retention_days: int = RETENTION_DAYS, limit: int = BATCH_LIMIT) -> int:
    """보관 기간이 지난 탈퇴 계정을 모두 파기하고, 파기한 개수를 돌려준다."""
    targets = await find_purge_targets(retention_days, limit)
    if not targets:
        return 0

    purged = 0
    for user_id in targets:
        try:
            if await purge_account(user_id):
                purged += 1
        except Exception as e:
            # 한 계정이 실패해도 나머지는 계속 처리한다
            logger.error(f"[account_purge] 계정 {user_id} 파기 실패: {e}")

    logger.info(f"[account_purge] 대상 {len(targets)}건 중 {purged}건 파기 (보관 {retention_days}일)")
    return purged


# 주기 실행 간격 (초). 하루 한 번이면 충분하지만, 서버 재시작이 잦아도
# 놓치지 않도록 6시간마다 확인한다.
PURGE_INTERVAL_SECONDS = 6 * 60 * 60


async def purge_loop():
    """탈퇴 계정 파기를 주기적으로 실행하는 백그라운드 루프.

    어떤 실패도 서버를 멈추면 안 되므로 예외를 삼키고 다음 주기를 기다린다.
    """
    import asyncio

    while True:
        try:
            await purge_expired_accounts()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"[account_purge] 주기 실행 실패: {e}")
        await asyncio.sleep(PURGE_INTERVAL_SECONDS)
