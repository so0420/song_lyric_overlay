"""업로드 음원 파기 — 점검/수동 실행 스크립트.

서버가 켜져 있으면 6시간마다 자동으로 돌지만, 무엇이 지워질지 먼저 눈으로 확인하거나
수동으로 한 번 돌리고 싶을 때 쓴다.

사용법:
    python purge_audio.py               # 대상만 보여준다 (기본: 아무것도 지우지 않음)
    python purge_audio.py --days 7      # 유예 기간을 바꿔서 대상 확인
    python purge_audio.py --apply       # 실제로 파기한다
    python purge_audio.py --verify      # DB 와 디스크의 불일치(드리프트) 점검

--verify 가 필요한 이유:
    storage/ 는 DB 덤프에 들어있지 않다. DB 만 복원하면 '행은 있는데 파일이 없는' 상태가,
    파기 중 중단되면 '파일은 있는데 행이 없는' 상태가 생긴다. 둘 다 조용히 잘못 동작한다.
"""
import argparse
import asyncio

from dotenv import load_dotenv

load_dotenv()

from app.database.audio_purge import (  # noqa: E402
    ORPHAN_RETENTION_DAYS,
    purge_unlinked,
    sweep_temp_files,
)
from app.database.audio_repository import AudioRepository  # noqa: E402
from app.database.mariadb import db_handler  # noqa: E402
from app.utils.audio_storage import AUDIO_ROOT, AUDIO_TMP, resolve_audio_path  # noqa: E402


def _fmt_size(n):
    n = int(n or 0)
    if n >= 1024 * 1024:
        return f"{n / 1024 / 1024:.1f}MB"
    return f"{n // 1024}KB"


async def preview(days: int):
    repo = AudioRepository()
    targets = await repo.find_unlinked(days, 10000)
    stranded = await repo.find_marked_deleted(10000)

    total = await db_handler.fetch_one(
        "SELECT COUNT(*) AS c, COALESCE(SUM(byte_size),0) AS b "
        "FROM audio_files WHERE deleted_at IS NULL"
    )
    print(f"저장 루트: {AUDIO_ROOT}")
    print(f"보관 중인 음원: {total['c']}건 ({_fmt_size(total['b'])})")
    print(f"유예 기간: {days}일")
    print(f"파기 대상(미연결): {len(targets)}건")
    if stranded:
        print(f"파기 중단 잔여분: {len(stranded)}건 (다음 실행에서 회수)")

    if targets:
        print()
        detail = await db_handler.fetch_all(
            "SELECT id, original_filename, byte_size, created_at FROM audio_files "
            f"WHERE id IN ({','.join(str(t['id']) for t in targets)})"
        )
        print(f"{'ID':>8}  {'업로드일':<20} {'크기':>8}  파일명")
        print("-" * 80)
        for d in detail:
            print(f"{d['id']:>8}  {str(d['created_at']):<20} {_fmt_size(d['byte_size']):>8}  "
                  f"{d['original_filename'] or '(없음)'}")
    return targets


async def verify():
    """DB ↔ 디스크 양방향 드리프트 점검"""
    rows = await db_handler.fetch_all(
        "SELECT id, storage_path, original_filename FROM audio_files WHERE deleted_at IS NULL"
    )
    missing = []
    known = set()
    for r in rows:
        try:
            path = resolve_audio_path(r["storage_path"])
        except ValueError:
            missing.append((r["id"], r["storage_path"], "경로 이상"))
            continue
        known.add(path)
        if not path.exists():
            missing.append((r["id"], r["storage_path"], "파일 없음"))

    orphans = []
    if AUDIO_ROOT.exists():
        for path in AUDIO_ROOT.rglob("*"):
            if not path.is_file():
                continue
            if AUDIO_TMP in path.parents:
                continue
            if path not in known:
                orphans.append(path)

    print(f"DB 기록: {len(rows)}건")
    print(f"디스크에 없는 기록: {len(missing)}건  (재생 시 404)")
    for audio_id, sp, why in missing[:50]:
        print(f"   id={audio_id}  {sp}  — {why}")
    print(f"기록에 없는 파일: {len(orphans)}건  (낭비되는 용량)")
    total = 0
    for path in orphans[:50]:
        size = path.stat().st_size
        total += size
        print(f"   {path.relative_to(AUDIO_ROOT)}  {_fmt_size(size)}")
    if orphans:
        allsize = sum(p.stat().st_size for p in orphans)
        print(f"   합계 {_fmt_size(allsize)}")
    if not missing and not orphans:
        print("\n불일치 없음.")


async def main(days: int, apply: bool, do_verify: bool):
    await db_handler.initialize()
    try:
        if do_verify:
            await verify()
            return

        targets = await preview(days)

        if not apply:
            print()
            print("확인만 했습니다. 실제로 지우려면 --apply 를 붙여 실행하세요.")
            return

        if not targets:
            print("\n파기할 대상이 없습니다.")
            await sweep_temp_files()
            return

        answer = input(f"\n{len(targets)}건의 음원 파일을 파기합니다. 되돌릴 수 없습니다. 진행할까요? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            print("취소했습니다.")
            return

        await sweep_temp_files()
        purged = await purge_unlinked(retention_days=days, limit=len(targets) + 100)
        print(f"\n{purged}건 파기 완료.")
    finally:
        await db_handler.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=ORPHAN_RETENTION_DAYS,
                   help=f"미연결 유예 기간(일). 기본 {ORPHAN_RETENTION_DAYS}")
    p.add_argument("--apply", action="store_true", help="실제로 파기한다 (없으면 확인만)")
    p.add_argument("--verify", action="store_true", help="DB 와 디스크의 불일치만 점검한다")
    args = p.parse_args()
    asyncio.run(main(args.days, args.apply, args.verify))
