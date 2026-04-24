-- 가사 공개 범위(visibility) 마이그레이션
-- is_public(0/1) → visibility ENUM('public','private','whitelist')
-- 화이트리스트 테이블 추가
-- 실행 전 반드시 백업할 것!

-- 1. visibility 컬럼 추가
ALTER TABLE song_lyrics
    ADD COLUMN visibility ENUM('public','private','whitelist') NOT NULL DEFAULT 'public' AFTER is_public;

-- 2. 기존 is_public 값 마이그레이션
UPDATE song_lyrics
    SET visibility = IF(is_public = 1, 'public', 'private');

-- 3. 기존 is_public 컬럼 제거
ALTER TABLE song_lyrics DROP COLUMN is_public;

-- 4. 인덱스 추가
CREATE INDEX idx_lyrics_visibility ON song_lyrics(visibility);

-- 5. 화이트리스트 테이블
CREATE TABLE IF NOT EXISTS `lyrics_whitelist` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `lyrics_id` BIGINT NOT NULL COMMENT 'song_lyrics 테이블 참조 ID',
    `user_id` BIGINT NOT NULL COMMENT 'users 테이블 참조 ID',
    `granted_by` BIGINT NULL COMMENT '화이트리스트에 추가한 관리자 ID',
    `granted_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY `uq_lyrics_user` (`lyrics_id`, `user_id`),

    CONSTRAINT `fk_wl_lyrics`  FOREIGN KEY (`lyrics_id`)  REFERENCES `song_lyrics`(`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_wl_user`    FOREIGN KEY (`user_id`)    REFERENCES `users`(`id`)       ON DELETE CASCADE,
    CONSTRAINT `fk_wl_grantor` FOREIGN KEY (`granted_by`) REFERENCES `users`(`id`)       ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_wl_user_id ON lyrics_whitelist(user_id);
