-- ============================================
-- 치지직(Chzzk) 연동 마이그레이션 (jamkubot 위임 방식)
-- ============================================
-- 적용 안내:
--   * 이미 운영 중인 DB에 치지직 연동 테이블을 추가할 때 실행하세요.
--     예) python migrate.py --file chzzk
--   * 신규 설치라면 schema.sql 에 동일 DDL이 포함되어 있어 실행할 필요가 없습니다.
--   * OAuth/토큰 관리는 jamkubot 이 대행하므로 우리는 유저 ↔ 치지직 채널 uid 매핑만 저장합니다.
--     (앱 자격증명/토큰을 DB에 두지 않습니다.)
--   * 선행 조건: users 테이블이 존재해야 합니다.
-- ============================================

-- 유저별 치지직 채널 연동 (uid 매핑)
CREATE TABLE IF NOT EXISTS `user_chzzk_channels` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `user_id` BIGINT NOT NULL COMMENT 'users 테이블 참조 ID',
    `channel_id` VARCHAR(100) NOT NULL COMMENT '치지직 채널 ID (UID)',
    `channel_name` VARCHAR(100) NULL COMMENT '치지직 채널 이름 (있으면 저장)',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY `unique_chzzk_user` (`user_id`),
    INDEX `idx_chzzk_channel_id` (`channel_id`),
    CONSTRAINT `fk_chzzk_channel_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
