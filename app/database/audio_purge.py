"""업로드 음원의 자동 파기 (미연결 파일 회수).

어떤 살아있는 가사·수록곡에도 연결되어 있지 않은 음원을 지운다. 유예 기간을 두는
이유는 편집기에서 음원을 올린 뒤 아직 저장(=가사 연결)하지 않은 파일을 곧바로
지워버리지 않기 위해서다.

유예 기간의 기준은 **업로드 시각(created_at)** 이지 '연결이 해제된 시각'이 아니다.
즉 업로드 후 7일이 이미 지난 파일은 연결이 끊기는 즉시(다음 주기에) 회수된다.
연결 해제 시점 기준으로 바꾸려면 unlinked_at 컬럼이 필요하며, 그때는 약관 제10조
제3항과 개인정보 처리방침(제2조 표·제8조 표)의 문구도 함께 고쳐야 한다.

'연결됨'의 정의:
    삭제되지 않은(deleted_at IS NULL) 가사, 또는 노래책 수록곡이 참조 중.
    소프트 삭제된 가사는 음원을 지켜주지 않는다 — 파기를 우선한다.
    (개인정보 처리방침의 파기 조항과 같아야 한다)

파기 순서가 중요하다. 파일당 3단계로 진행해서 중간에 죽어도 상태가 어긋나지 않게 한다.
    ① deleted_at 을 세워 선점한다 (이 시점부터 새 연결이 거부된다)
    ② 트랜잭션 **밖에서** 디스크 파일을 지운다 (파일 I/O 를 트랜잭션에 넣지 않는다)
    ③ 행을 지운다 (FK 의 ON DELETE SET NULL 이 잔여 참조를 정리한다)
  ①~③ 사이에서 죽으면 deleted_at 만 남은 행이 되고, 다음 주기가 회수한다.
"""
import asyncio
import os
import time

import anyio

from app.database.audio_repository import AudioRepository
# 모듈 자체를 참조한다 — 이름을 직접 import 하면 테스트에서 저장 루트를 갈아끼울 수 없다
from app.utils import audio_storage
from app.utils.log import logger

# 어느 가사에도 연결되지 않은 파일을 지우기까지의 유예 기간
ORPHAN_RETENTION_DAYS = 7

# 한 번에 처리할 최대 파일 수 (실수가 있어도 한 번에 전부 날아가지 않게 하는 안전장치)
BATCH_LIMIT = 200

# 업로드 도중 끊긴 임시 파일을 지우기까지의 시간
TMP_MAX_AGE_SECONDS = 24 * 60 * 60

PURGE_INTERVAL_SECONDS = 6 * 60 * 60


async def _unlink(storage_path: str) -> None:
    """디스크 파일 삭제 (없으면 조용히 통과). 이벤트 루프를 막지 않는다."""
    try:
        path = audio_storage.resolve_audio_path(storage_path)
    except ValueError as e:
        logger.error(f"[audio_purge] 경로가 이상해 건너뜀: {e}")
        return
    await anyio.to_thread.run_sync(lambda: path.unlink(missing_ok=True))


async def purge_one(
    audio_id: int,
    storage_path: str,
    repo: AudioRepository,
    claim: bool = True,
    retention_days: int = ORPHAN_RETENTION_DAYS,
) -> bool:
    """음원 한 건을 파기한다 (선점 → 파일 삭제 → 행 삭제).

    선점은 '아직 미연결인가'를 UPDATE 안에서 다시 확인한다. 대상 목록을 뽑은 뒤
    실제로 지우기 전 사이에 사용자가 그 음원을 가사에 연결했을 수 있기 때문이다.
    claim=False 는 앞 주기에서 이미 선점된 채 남은 행을 뒷정리할 때만 쓴다.
    """
    if claim and not await repo.claim_unlinked_for_purge(audio_id, retention_days):
        return False  # 그 사이 연결됐거나, 다른 곳에서 선점했거나, 이미 파기됨
    await _unlink(storage_path)
    await repo.hard_delete(audio_id)
    return True


async def purge_unlinked(
    retention_days: int = ORPHAN_RETENTION_DAYS,
    limit: int = BATCH_LIMIT,
    repo: AudioRepository = None,
) -> int:
    """미연결 음원과, 앞선 주기에서 중간에 끊긴 항목을 파기하고 건수를 돌려준다."""
    repo = repo or AudioRepository()

    # ① 앞 주기에서 ②~③ 사이에 끊긴 것들 뒷정리 (이미 선점된 상태)
    purged = 0
    for row in await repo.find_marked_deleted(limit):
        try:
            if await purge_one(row["id"], row["storage_path"], repo, claim=False):
                purged += 1
        except Exception as e:
            logger.error(f"[audio_purge] 잔여 파기 실패 (id={row['id']}): {e}")

    # ② 유예 기간이 지난 미연결 파일
    targets = await repo.find_unlinked(retention_days, limit)
    for row in targets:
        try:
            if await purge_one(row["id"], row["storage_path"], repo, retention_days=retention_days):
                purged += 1
        except Exception as e:
            logger.error(f"[audio_purge] 파기 실패 (id={row['id']}): {e}")

    if purged:
        logger.info(f"[audio_purge] 음원 {purged}건 파기 (미연결 {retention_days}일 경과)")
    return purged


def _sweep_temp_files() -> int:
    """업로드 중 끊겨 남은 .part 파일 정리 (동기 함수 — 스레드에서 호출한다)."""
    tmp_dir = audio_storage.AUDIO_TMP
    if not tmp_dir.exists():
        return 0
    removed = 0
    cutoff = time.time() - TMP_MAX_AGE_SECONDS
    for path in tmp_dir.glob("*.part"):
        try:
            if path.stat().st_mtime < cutoff:
                os.unlink(path)
                removed += 1
        except OSError:
            pass
    return removed


async def sweep_temp_files() -> int:
    removed = await anyio.to_thread.run_sync(_sweep_temp_files)
    if removed:
        logger.info(f"[audio_purge] 중단된 업로드 임시 파일 {removed}건 정리")
    return removed


async def purge_loop():
    """미연결 음원 파기를 주기적으로 실행하는 백그라운드 루프.

    어떤 실패도 서버를 멈추면 안 되므로 예외를 삼키고 다음 주기를 기다린다.
    (account_purge.purge_loop 과 같은 구조)
    """
    while True:
        try:
            await sweep_temp_files()
            await purge_unlinked()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"[audio_purge] 주기 실행 실패: {e}")
        await asyncio.sleep(PURGE_INTERVAL_SECONDS)
