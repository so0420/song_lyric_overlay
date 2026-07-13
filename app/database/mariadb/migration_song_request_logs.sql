-- ============================================
-- 노래 신청 이력 로그 (통계 전용, append-only)
-- ============================================
-- 적용 안내:
--   python migrate.py --file song_request_logs
--
-- 배경:
--   song_requests 는 신청 큐라서 '이미 부른 신청 삭제'/'전체 삭제' 로 물리 삭제된다.
--   따라서 최근 1달 신청 횟수 같은 통계를 song_requests 에서 직접 세면
--   큐를 비운 만큼 과소 집계된다. 삭제와 무관한 영구 로그를 별도로 둔다.
--   (곡이 특정되는 신청만 기록 — song_id NOT NULL)
-- ============================================

CREATE TABLE IF NOT EXISTS `song_request_logs` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `streamer_id` BIGINT NOT NULL COMMENT 'streamers 테이블 참조 ID',
    `song_id` BIGINT NOT NULL COMMENT 'songs 테이블 참조 ID',
    `requested_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '신청 시각',
    INDEX `idx_reqlog_streamer_song_time` (`streamer_id`, `song_id`, `requested_at`),
    CONSTRAINT `fk_reqlog_streamer` FOREIGN KEY (`streamer_id`) REFERENCES `streamers` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_reqlog_song` FOREIGN KEY (`song_id`) REFERENCES `songs` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 아직 큐에 남아있는 기존 신청분을 로그로 백필 (곡이 특정된 것만)
INSERT INTO `song_request_logs` (`streamer_id`, `song_id`, `requested_at`)
SELECT `streamer_id`, `song_id`, `request_at`
FROM `song_requests`
WHERE `song_id` IS NOT NULL;
