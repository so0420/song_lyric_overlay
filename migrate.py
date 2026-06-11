"""DB 마이그레이션 적용 스크립트

`.env` 의 DB 설정(app.utils.config.Settings)을 읽어 MariaDB 에 마이그레이션 SQL 을 적용한다.
이 프로젝트는 별도 마이그레이션 도구가 없으므로, 운영/개발 DB 에 신규 테이블·컬럼을 반영할 때 사용한다.

사용법:
    python migrate.py                 # 적용 안 된 마이그레이션을 순서대로 적용
    python migrate.py --list          # 마이그레이션 목록과 적용 여부만 출력
    python migrate.py --file songbook # 특정 마이그레이션만 적용 (파일명 부분 일치)
    python migrate.py --yes           # 확인 프롬프트 없이 적용
    python migrate.py --baseline      # 실행 없이 '적용됨'으로만 기록 (기존 DB에 도입 시)

이미 운영 중인 DB (legacy 마이그레이션이 수동 적용된 경우):
    1) python migrate.py --baseline --file lyrics_visibility --yes   # 기존 것 기록
       python migrate.py --baseline --file remove_itunes --yes
    2) python migrate.py --file songbook --yes   # 신규만 적용
       python migrate.py --file chzzk --yes
    이후로는 python migrate.py 만으로 새 마이그레이션이 안전하게 적용됩니다.

동작 방식:
    * app/database/mariadb/migration_*.sql 파일을 파일명 순으로 적용한다.
    * `schema_migrations` 테이블에 적용 이력을 기록해, 이미 적용된 파일은 건너뛴다.
    * 각 파일은 하나의 트랜잭션으로 실행되며, 실패 시 해당 파일 변경은 롤백된다.
      (단, MariaDB 는 DDL 이 암묵적 커밋을 유발하므로 CREATE/ALTER 중간 실패 시
       부분 적용이 남을 수 있다 — 적용 전 백업을 권장한다.)
"""
import argparse
import sys
from pathlib import Path

import pymysql

# .env 로딩을 위해 프로젝트 설정 사용
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.utils.config import settings  # noqa: E402

MIGRATIONS_DIR = Path(__file__).resolve().parent / "app" / "database" / "mariadb"

CREATE_MIGRATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS `schema_migrations` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `filename` VARCHAR(255) NOT NULL UNIQUE COMMENT '적용된 마이그레이션 파일명',
    `applied_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '적용 일시'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


def connect():
    host = settings.db_host
    if host == "localhost":
        host = "127.0.0.1"  # Windows 호환
    return pymysql.connect(
        host=host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password or "",
        db=settings.db_name,
        charset="utf8mb4",
        autocommit=False,
    )


def split_statements(sql: str):
    """SQL 텍스트를 개별 문장으로 분리 (주석/빈 줄 제거, 세미콜론 기준)

    이 프로젝트 마이그레이션은 단순 DDL/DML 만 쓰므로 문자열 리터럴 내 세미콜론은
    고려하지 않는다. 라인 주석(--) 과 빈 줄을 제거한 뒤 세미콜론으로 나눈다.
    """
    lines = []
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped.startswith("--") or not stripped:
            continue
        lines.append(line)
    cleaned = "\n".join(lines)
    return [s.strip() for s in cleaned.split(";") if s.strip()]


def discover_migrations(name_filter: str | None):
    files = sorted(MIGRATIONS_DIR.glob("migration_*.sql"))
    if name_filter:
        files = [f for f in files if name_filter in f.name]
    return files


def applied_set(conn) -> set:
    with conn.cursor() as cur:
        cur.execute(CREATE_MIGRATIONS_TABLE)
        conn.commit()
        cur.execute("SELECT filename FROM schema_migrations")
        return {row[0] for row in cur.fetchall()}


def apply_migration(conn, path: Path):
    statements = split_statements(path.read_text(encoding="utf-8"))
    with conn.cursor() as cur:
        for stmt in statements:
            cur.execute(stmt)
        cur.execute(
            "INSERT INTO schema_migrations (filename) VALUES (%s)", (path.name,)
        )
    conn.commit()


def main():
    parser = argparse.ArgumentParser(description="DB 마이그레이션 적용")
    parser.add_argument("--list", action="store_true", help="목록과 적용 여부만 출력")
    parser.add_argument("--file", help="파일명에 이 문자열이 포함된 마이그레이션만 대상으로 함")
    parser.add_argument("--yes", action="store_true", help="확인 프롬프트 없이 적용")
    parser.add_argument(
        "--baseline",
        action="store_true",
        help="대상 마이그레이션을 '실행하지 않고' 적용된 것으로 기록 "
        "(이미 수동 적용된 기존 DB에 이력 추적을 도입할 때 사용)",
    )
    args = parser.parse_args()

    files = discover_migrations(args.file)
    if not files:
        print("적용할 마이그레이션 파일이 없습니다.")
        return

    conn = connect()
    try:
        done = applied_set(conn)

        print(f"DB: {settings.db_user}@{settings.db_host}:{settings.db_port}/{settings.db_name}\n")
        pending = []
        for f in files:
            mark = "applied" if f.name in done else "pending"
            print(f"  [{mark}] {f.name}")
            if f.name not in done:
                pending.append(f)

        if args.list:
            return

        # --baseline: 실행 없이 적용 이력만 기록
        if args.baseline:
            if not pending:
                print("\n기록할 미적용 마이그레이션이 없습니다.")
                return
            print(f"\n다음 {len(pending)}개를 '실행 없이' 적용 완료로 기록합니다:")
            for f in pending:
                print(f"  - {f.name}")
            if not args.yes:
                answer = input("계속할까요? [y/N] ").strip().lower()
                if answer not in ("y", "yes"):
                    print("취소했습니다.")
                    return
            with conn.cursor() as cur:
                for f in pending:
                    cur.execute("INSERT INTO schema_migrations (filename) VALUES (%s)", (f.name,))
            conn.commit()
            print("기록 완료.")
            return
        if not pending:
            print("\n모든 마이그레이션이 이미 적용되어 있습니다.")
            return

        print(f"\n적용 대기: {len(pending)}개")
        if not args.yes:
            answer = input("적용하시겠습니까? 적용 전 DB 백업을 권장합니다. [y/N] ").strip().lower()
            if answer not in ("y", "yes"):
                print("취소했습니다.")
                return

        for f in pending:
            print(f"  -> 적용 중: {f.name}")
            try:
                apply_migration(conn, f)
            except Exception as e:
                conn.rollback()
                print(f"  [실패] {f.name}\n    {e}")
                print("    중단합니다. (이미 실행된 DDL 은 MariaDB 특성상 롤백되지 않을 수 있습니다)")
                sys.exit(1)
            print(f"  [완료] {f.name}")

        print("\n마이그레이션 적용 완료.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
