"""탈퇴 계정 개인정보 파기 — 점검/수동 실행 스크립트.

서버가 켜져 있으면 6시간마다 자동으로 돌지만, 배포 직후 무엇이 지워질지
먼저 눈으로 확인하거나 수동으로 한 번 돌리고 싶을 때 쓴다.

사용법:
    python purge_accounts.py                # 대상만 보여준다 (기본: 아무것도 지우지 않음)
    python purge_accounts.py --days 30      # 보관 기간을 바꿔서 대상 확인
    python purge_accounts.py --apply        # 실제로 파기한다
"""
import argparse
import asyncio

from dotenv import load_dotenv

load_dotenv()

from app.database.account_purge import RETENTION_DAYS, purge_expired_accounts  # noqa: E402
from app.database.mariadb import db_handler  # noqa: E402


PREVIEW_SQL = """
    SELECT u.id,
           u.email,
           u.name,
           u.deleted_at,
           (u.password_hash IS NOT NULL) AS has_password,
           (u.overlay_token IS NOT NULL) AS has_overlay_token,
           (SELECT COUNT(*) FROM social_accounts s WHERE s.user_id = u.id) AS social_count
      FROM users u
     WHERE u.deleted_at IS NOT NULL
       AND u.purged_at IS NULL
       AND u.deleted_at < (NOW() - INTERVAL %s DAY)
     ORDER BY u.deleted_at
"""

PENDING_SQL = """
    SELECT COUNT(*) AS c
      FROM users
     WHERE deleted_at IS NOT NULL
       AND purged_at IS NULL
       AND deleted_at >= (NOW() - INTERVAL %s DAY)
"""


def _mask(email):
    """이메일을 부분만 보여준다 (콘솔·로그에 원문을 남기지 않기 위해)."""
    if not email:
        return "(없음)"
    name, _, domain = email.partition("@")
    head = name[:2] if len(name) > 2 else name[:1]
    return f"{head}{'*' * max(1, len(name) - len(head))}@{domain}"


async def main(days: int, apply: bool):
    await db_handler.initialize()
    try:
        targets = await db_handler.fetch_all(PREVIEW_SQL, (days,))
        pending = await db_handler.fetch_one(PENDING_SQL, (days,))

        print(f"보관 기간: {days}일")
        print(f"아직 기간이 안 지난 탈퇴 계정: {pending['c']}건 (복구 가능)")
        print(f"파기 대상: {len(targets)}건")

        if targets:
            print()
            print(f"{'ID':>8}  {'탈퇴일':<20} {'이메일':<28} {'이름':<12} 비번 토큰 소셜")
            print("-" * 92)
            for t in targets:
                print(
                    f"{t['id']:>8}  {str(t['deleted_at']):<20} {_mask(t['email']):<28} "
                    f"{(t['name'] or '(없음)'):<12} "
                    f"{'O' if t['has_password'] else '-':^4} "
                    f"{'O' if t['has_overlay_token'] else '-':^4} "
                    f"{t['social_count']:^4}"
                )

        if not apply:
            print()
            print("확인만 했습니다. 실제로 지우려면 --apply 를 붙여 실행하세요.")
            return

        if not targets:
            print("\n파기할 대상이 없습니다.")
            return

        answer = input(f"\n{len(targets)}건의 개인정보를 파기합니다. 되돌릴 수 없습니다. 진행할까요? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            print("취소했습니다.")
            return

        purged = await purge_expired_accounts(retention_days=days, limit=len(targets))
        print(f"\n{purged}건 파기 완료.")
    finally:
        await db_handler.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=RETENTION_DAYS, help=f"보관 기간(일). 기본 {RETENTION_DAYS}")
    p.add_argument("--apply", action="store_true", help="실제로 파기한다 (없으면 확인만)")
    args = p.parse_args()
    asyncio.run(main(args.days, args.apply))
