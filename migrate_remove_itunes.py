"""
iTunes 제거 마이그레이션 스크립트

수행 작업:
1. MariaDB: artists, songs 테이블의 it_ 프리픽스를 custom_으로 변환
2. Meilisearch: 기존 인덱스 삭제 후 DB 기반으로 재구축

실행 방법:
  python migrate_remove_itunes.py

실행 전 반드시 DB 백업할 것!
"""

import asyncio
from app.database.mariadb import db_handler
from app.database.meilisearch.meilisearch import meilisearch_handler


async def migrate_db():
    """MariaDB: it_ → custom_ 프리픽스 변환"""
    print("[DB] 마이그레이션 시작...")

    # 변환 대상 확인
    artist_count = await db_handler.fetch_one(
        "SELECT COUNT(*) as cnt FROM artists WHERE artist_external_id LIKE 'it\\_%'"
    )
    song_count = await db_handler.fetch_one(
        "SELECT COUNT(*) as cnt FROM songs WHERE song_external_id LIKE 'it\\_%'"
    )
    print(f"[DB] 변환 대상: 아티스트 {artist_count['cnt']}건, 노래 {song_count['cnt']}건")

    if artist_count['cnt'] == 0 and song_count['cnt'] == 0:
        print("[DB] 변환할 데이터가 없습니다. 건너뜁니다.")
        return

    # 아티스트 변환
    result = await db_handler.execute_query(
        """
        UPDATE artists
        SET artist_external_id = CONCAT('custom_', SUBSTRING(artist_external_id, 4))
        WHERE artist_external_id LIKE 'it\\_%'
        """
    )
    print(f"[DB] 아티스트 변환 완료: {artist_count['cnt']}건")

    # 노래 변환
    result = await db_handler.execute_query(
        """
        UPDATE songs
        SET song_external_id = CONCAT('custom_', SUBSTRING(song_external_id, 4))
        WHERE song_external_id LIKE 'it\\_%'
        """
    )
    print(f"[DB] 노래 변환 완료: {song_count['cnt']}건")


async def rebuild_meilisearch():
    """Meilisearch: 기존 인덱스 삭제 후 DB 데이터로 재구축"""
    print("[Meilisearch] 인덱스 재구축 시작...")

    # 기존 인덱스 삭제
    if await meilisearch_handler.index_exists():
        await meilisearch_handler.delete_index()
        print("[Meilisearch] 기존 인덱스 삭제 완료")

    # 인덱스 재생성 + 설정
    await meilisearch_handler.initialize()
    print("[Meilisearch] 인덱스 생성 완료")

    # DB에서 모든 노래 조회
    songs = await db_handler.fetch_all(
        """
        SELECT s.song_external_id, s.title, a.name as singer,
               s.cover_image_url as image_url, s.owner_id
        FROM songs s
        LEFT JOIN artists a ON s.artist_id = a.id
        WHERE s.song_external_id IS NOT NULL
        """
    )

    if not songs:
        print("[Meilisearch] 인덱싱할 노래가 없습니다.")
        return

    # 배치로 인덱싱 (100개씩)
    batch_size = 100
    total = len(songs)
    indexed = 0

    for i in range(0, total, batch_size):
        batch = songs[i:i + batch_size]
        documents = []
        for s in batch:
            documents.append({
                "id": s['song_external_id'],
                "title": s['title'] or '',
                "singer": s['singer'] or '',
                "image_url": s['image_url'],
                "owner_id": s['owner_id']
            })
        await meilisearch_handler.add_documents(documents)
        indexed += len(batch)
        print(f"[Meilisearch] 인덱싱 진행: {indexed}/{total}")

    print(f"[Meilisearch] 인덱스 재구축 완료: 총 {total}건")


async def main():
    print("=" * 50)
    print("iTunes 제거 마이그레이션")
    print("=" * 50)

    # 초기화
    await db_handler.initialize()

    try:
        # 1. DB 마이그레이션
        await migrate_db()
        print()

        # 2. Meilisearch 재구축
        await rebuild_meilisearch()

        print()
        print("=" * 50)
        print("마이그레이션 완료!")
        print("=" * 50)
    finally:
        await db_handler.close()
        await meilisearch_handler.close()


if __name__ == "__main__":
    asyncio.run(main())
