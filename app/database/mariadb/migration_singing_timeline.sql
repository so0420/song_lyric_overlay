-- ============================================
-- 노래 타임라인 기록 (노래하기 페이지에서 방송 중 곡 타임스탬프 기록)
-- ============================================
-- 적용 안내:
--   python migrate.py --file singing_timeline
--
-- 배경:
--   치지직 연동 유저가 방송 중 부른 곡을 '방송 시작(openDate) 기준 경과 시간'과 함께
--   기록해 두는 용도. 방송별로 openDate 로 묶어서 조회하며, 클립보드용 타임라인을 만든다.
--   최근 1달치만 보관한다(기록 시 오래된 행을 정리).
-- ============================================

CREATE TABLE IF NOT EXISTS `singing_timeline_records` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `user_id` BIGINT NOT NULL COMMENT 'users 테이블 참조 ID',
    `open_date` DATETIME NOT NULL COMMENT '방송 시작 시각 (치지직 content.openDate, KST) — 방송 구분 키',
    `elapsed_seconds` INT NOT NULL COMMENT '방송 시작 기준 경과 초',
    `title` VARCHAR(255) NOT NULL COMMENT '기록 시점의 곡 제목 (커스텀 편집 가능)',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '기록 시각',
    INDEX `idx_timeline_user_open` (`user_id`, `open_date`),
    INDEX `idx_timeline_created` (`created_at`),
    CONSTRAINT `fk_timeline_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
