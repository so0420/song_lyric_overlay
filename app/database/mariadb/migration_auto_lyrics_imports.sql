-- ============================================
-- 자동 가사(LRCLIB) 적용 기록 / 관리자 정식 등록 대기 큐
-- ============================================
-- 적용 안내:
--   python migrate.py --file auto_lyrics
--
-- 배경:
--   노래하기 탭에서 가사가 없는 곡에 대해 LRCLIB 싱크 가사를 즉시 적용할 수 있다.
--   자동 가사는 곡별로 '이 곡만 오프셋' 을 맞춰 사용하는데, 그 결과(가사 + 맞춘 오프셋)를
--   여기에 기록해 두면 관리자가 나중에 검토 후 그대로 정식 가사(song_lyrics, is_verified=1)로
--   등록할 수 있다. 즉 이 테이블은 '자동 가사 사용 로그' 이자 '정식 등록 대기 큐' 역할.
--   (같은 사용자·곡·출처 조합은 UNIQUE 로 묶어 재적용/오프셋 재조정 시 같은 행을 갱신한다)
-- ============================================

CREATE TABLE IF NOT EXISTS `auto_lyrics_imports` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `user_id` BIGINT NULL COMMENT '자동 가사를 적용한 사용자 ID (삭제 시 NULL)',
    `song_id` BIGINT NOT NULL COMMENT 'songs 테이블 참조 ID',
    `source` VARCHAR(20) NOT NULL DEFAULT 'lrclib' COMMENT '가사 출처',
    `source_id` VARCHAR(64) NULL COMMENT '출처 측 고유 ID (LRCLIB track id)',
    `track_name` VARCHAR(255) NULL COMMENT '출처 트랙명 (관리자 참고용)',
    `artist_name` VARCHAR(255) NULL COMMENT '출처 아티스트명 (관리자 참고용)',
    `album_name` VARCHAR(255) NULL COMMENT '출처 앨범명 (관리자 참고용)',
    `duration` INT NULL COMMENT '출처 트랙 길이 (초)',
    `synced_lyrics` MEDIUMTEXT NULL COMMENT 'LRCLIB 원본 LRC 텍스트 (출처 보존)',
    `lyrics_data` MEDIUMTEXT NULL COMMENT '변환된 가사 JSON [{"start","end","text"}] (오프셋 미적용 기준본)',
    `offset_ms` INT NOT NULL DEFAULT 0 COMMENT "사용자가 맞춘 '이 곡만 오프셋' (ms)",
    `mr_youtube_video_id` VARCHAR(255) NULL COMMENT '싱크 맞출 때 사용한 영상 ID (오프셋 기준)',
    `status` ENUM('pending','registered','ignored') NOT NULL DEFAULT 'pending' COMMENT '검토 상태',
    `registered_lyrics_id` BIGINT NULL COMMENT '정식 등록된 song_lyrics ID',
    `reviewed_by` BIGINT NULL COMMENT '검토/등록한 관리자 ID',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- 같은 사용자·곡·출처 조합은 하나로 (재적용/오프셋 재조정 시 upsert)
    UNIQUE KEY `uq_auto_lyrics_user_song_source` (`user_id`, `song_id`, `source_id`),

    INDEX `idx_auto_lyrics_status` (`status`),
    INDEX `idx_auto_lyrics_song_id` (`song_id`),
    INDEX `idx_auto_lyrics_created_at` (`created_at`),

    CONSTRAINT `fk_auto_lyrics_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE SET NULL,
    CONSTRAINT `fk_auto_lyrics_song` FOREIGN KEY (`song_id`) REFERENCES `songs` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_auto_lyrics_registered` FOREIGN KEY (`registered_lyrics_id`) REFERENCES `song_lyrics` (`id`) ON DELETE SET NULL,
    CONSTRAINT `fk_auto_lyrics_reviewer` FOREIGN KEY (`reviewed_by`) REFERENCES `users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
