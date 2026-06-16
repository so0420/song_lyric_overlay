-- ============================================
-- 재생목록 DB 저장 (User Playlist) 마이그레이션
-- ============================================
-- 적용 안내:
--   * 이미 운영 중인 DB에 재생목록 DB 저장 기능을 추가할 때 이 파일을 수동으로 실행하세요.
--     예) mysql -u <user> -p <db_name> < app/database/mariadb/migration_playlist.sql
--   * 신규 설치라면 schema.sql 에 동일한 DDL이 포함되어 있으므로 실행할 필요가 없습니다.
--   * CREATE TABLE IF NOT EXISTS 라서 중복 실행해도 안전합니다.
--   * 선행 조건: users 테이블이 존재해야 합니다 (외래 키 참조).
-- ============================================

-- 사용자별 재생목록 (한 행). playlist_json 은 [{lyricsId, songId, songTitle, artistName, videoId, coverImageUrl, ...}]
CREATE TABLE IF NOT EXISTS `user_playlists` (
    `user_id` BIGINT NOT NULL PRIMARY KEY COMMENT 'users 테이블 참조 ID',
    `playlist_json` TEXT NOT NULL COMMENT '재생목록 JSON 배열',
    `current_index` INT NOT NULL DEFAULT -1 COMMENT '현재 재생 중 인덱스 (-1=없음)',
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT `fk_playlist_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
