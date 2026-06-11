-- ============================================
-- 노래책 (Songbook) 기능 마이그레이션
-- ============================================
-- 적용 안내:
--   * 이미 운영 중인 DB에 노래책 기능 테이블을 추가할 때 이 파일을 수동으로 실행하세요.
--     예) mysql -u <user> -p <db_name> < app/database/mariadb/migration_songbook.sql
--   * 신규 설치라면 schema.sql 에 동일한 DDL이 포함되어 있으므로 이 파일은 실행할 필요가 없습니다.
--   * 모든 테이블은 CREATE TABLE IF NOT EXISTS 라서 중복 실행해도 안전합니다.
--   * 선행 조건: users, songs, song_lyrics 테이블이 존재해야 합니다 (외래 키 참조).
-- ============================================

-- 스트리머 노래책 프로필
CREATE TABLE IF NOT EXISTS `streamers` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `user_id` BIGINT NOT NULL COMMENT 'users 테이블 참조 ID',
    `streamer_id` VARCHAR(255) NOT NULL COMMENT '외부에 노출될 스트리머 ID (UUID)',
    `slug` VARCHAR(100) NOT NULL COMMENT '노래책 공개 주소 (URL slug)',
    `description` TEXT NULL COMMENT '스트리머 소개',
    `social_links` TEXT NOT NULL DEFAULT '[]' COMMENT '소셜 링크 JSON [{"name","url"}]',
    `tags` TEXT NOT NULL DEFAULT '[]' COMMENT '노래 태그(카테고리) 목록 JSON [{"name","color"}]',
    `request_enabled` TINYINT(1) DEFAULT 0 COMMENT '노래 신청 기능 전체 on/off',
    `request_web_enabled` TINYINT(1) DEFAULT 0 COMMENT '웹(노래책 페이지) 신청 on/off',
    `request_auto_playlist` TINYINT(1) DEFAULT 1 COMMENT '신청 곡 노래하기 재생목록 자동 추가 on/off',
    `request_chat_enabled` TINYINT(1) DEFAULT 0 COMMENT '(예약) 채팅 신청 on/off',
    `request_donation_enabled` TINYINT(1) DEFAULT 0 COMMENT '(예약) 후원 신청 on/off',
    `default_price_cheese` INT DEFAULT 0 COMMENT '(예약) 기본 신청 치즈 가격',
    `default_price_balloon` INT DEFAULT 0 COMMENT '(예약) 기본 신청 별풍선 가격',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY `unique_streamer_user_id` (`user_id`),
    UNIQUE KEY `unique_streamer_external_id` (`streamer_id`),
    UNIQUE KEY `unique_streamer_slug` (`slug`),
    CONSTRAINT `fk_streamer_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 노래책 수록곡
CREATE TABLE IF NOT EXISTS `streamer_songbooks` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `streamer_id` BIGINT NOT NULL COMMENT 'streamers 테이블 참조 ID',
    `sort_order` INT NOT NULL COMMENT '노래 정렬 순서',
    `song_id` BIGINT NOT NULL COMMENT 'songs 테이블 참조 ID',
    `mr_youtube_video_id` VARCHAR(255) NULL COMMENT 'MR 유튜브 영상 ID',
    `lyrics_id` BIGINT NULL COMMENT '연결된 가사 ID (song_lyrics)',
    `cover_image_url` TEXT NULL COMMENT '커버 이미지 URL',
    `tags` TEXT NOT NULL DEFAULT '[]' COMMENT '노래 태그 JSON ["tag1", ...] (streamers.tags의 name과 연결)',
    `difficulty` TINYINT NOT NULL DEFAULT 5 COMMENT '난이도 (1 ~ 10)',
    `memo` VARCHAR(255) NULL COMMENT '노래 설명/메모',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY `unique_streamer_song` (`streamer_id`, `song_id`),
    INDEX `idx_songbook_streamer_sort` (`streamer_id`, `sort_order`),
    INDEX `idx_songbook_song_id` (`song_id`),
    CONSTRAINT `fk_songbook_streamer` FOREIGN KEY (`streamer_id`) REFERENCES `streamers` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_songbook_song` FOREIGN KEY (`song_id`) REFERENCES `songs` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_songbook_lyrics` FOREIGN KEY (`lyrics_id`) REFERENCES `song_lyrics` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 노래 신청
CREATE TABLE IF NOT EXISTS `song_requests` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `streamer_id` BIGINT NOT NULL COMMENT 'streamers 테이블 참조 ID',
    `requester` VARCHAR(255) NOT NULL COMMENT '신청자 닉네임',
    `requester_type` ENUM('CHAT', 'DONATION', 'WEB', 'MANUAL') NOT NULL COMMENT '신청 경로',
    `requester_platform` VARCHAR(50) NULL COMMENT '신청자 플랫폼 (Web 등)',
    `sort_order` INT NOT NULL COMMENT '신청 순서',
    `status` ENUM('waiting', 'playing', 'done') DEFAULT 'waiting' COMMENT '상태: 대기중/부르는중/이미부름',
    `song_id` BIGINT NULL COMMENT 'songs 테이블 참조 ID (노래책 외 신청이면 NULL)',
    `title` VARCHAR(255) NULL COMMENT '노래 제목 (노래책 외 신청용)',
    `artist` VARCHAR(255) NULL COMMENT '아티스트 (노래책 외 신청용)',
    `delivered_at` TIMESTAMP NULL COMMENT '노래하기 재생목록 자동 추가 전달 시각 (NULL=미전달)',
    `request_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX `idx_song_request_streamer` (`streamer_id`, `status`, `sort_order`),
    CONSTRAINT `fk_song_request_streamer` FOREIGN KEY (`streamer_id`) REFERENCES `streamers` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_song_request_song` FOREIGN KEY (`song_id`) REFERENCES `songs` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
