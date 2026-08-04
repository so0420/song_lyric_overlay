-- ============================================
-- 가사 재생 음원 업로드 (audio_files)
-- ============================================
-- 적용 안내:
--   python migrate.py --file lyrics_audio
--
-- 배경:
--   지금까지 가사의 재생 소스는 song_lyrics.mr_youtube_video_id (유튜브 MR) 뿐이었다.
--   유튜브에 없는 MR(직접 만든 반주, 구매한 MR, 소장 음원)을 쓸 수 있도록,
--   이용자가 업로드한 음원 파일을 재생 소스로 연결할 수 있게 한다.
--   파일 본체는 서버 디스크(storage/audio)에 두고 여기에는 위치와 메타데이터만 둔다.
--
-- 접근 통제 원칙:
--   업로드 음원은 그 자체로 공개 범위를 갖지 않는다.
--   연결된 가사(song_lyrics.visibility)의 공개 범위를 따르며, 재생에는 로그인이 필요하다.
--
-- 선행 조건: users, song_lyrics, streamer_songbooks 테이블이 있어야 한다.
-- 주의: migrate.py 의 split_statements 는 문자열 리터럴을 인식하지 못하므로
--       COMMENT 문자열 안에 세미콜론을 쓰지 말 것.
-- ============================================

CREATE TABLE IF NOT EXISTS `audio_files` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `owner_id` BIGINT NULL COMMENT '업로드한 사용자 ID. 탈퇴/삭제 시 NULL',
    `storage_path` VARCHAR(255) NOT NULL COMMENT '저장 루트 기준 상대 경로 (예 ab/cd/abcd....mp3)',
    `original_filename` VARCHAR(255) NULL COMMENT '업로드 당시 원본 파일명 (표시용)',
    `mime_type` VARCHAR(100) NOT NULL COMMENT '서버가 매직바이트로 판별한 실제 형식. 클라이언트 신고값은 저장하지 않음',
    `byte_size` BIGINT NOT NULL COMMENT '파일 크기 (바이트)',
    `sha256` CHAR(64) NOT NULL COMMENT '내용 해시. 같은 소유자의 중복 업로드 판별용',
    `duration_ms` INT NULL COMMENT '재생 길이 (밀리초). 클라이언트가 알려준 표시용 값이며 서버는 검증하지 않음',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    `deleted_at` TIMESTAMP NULL COMMENT '파기 표시. 값이 있으면 디스크 파일은 이미 지워졌거나 지우는 중',

    UNIQUE KEY `uq_audio_storage_path` (`storage_path`),
    UNIQUE KEY `uq_audio_owner_sha256` (`owner_id`, `sha256`),
    INDEX `idx_audio_owner_quota` (`owner_id`, `deleted_at`, `byte_size`),
    INDEX `idx_audio_reap` (`deleted_at`, `created_at`),

    CONSTRAINT `fk_audio_owner` FOREIGN KEY (`owner_id`) REFERENCES `users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 가사 ↔ 음원 연결 (mr_youtube_video_id 와 택일)
ALTER TABLE `song_lyrics`
    ADD COLUMN `audio_file_id` BIGINT NULL COMMENT '업로드 음원 ID. mr_youtube_video_id 와 택일' AFTER `mr_youtube_video_id`,
    ADD INDEX `idx_lyrics_audio_file` (`audio_file_id`),
    ADD CONSTRAINT `fk_lyrics_audio` FOREIGN KEY (`audio_file_id`) REFERENCES `audio_files` (`id`) ON DELETE SET NULL;

-- 노래책 수록곡 전용 음원 (가사의 음원보다 우선)
ALTER TABLE `streamer_songbooks`
    ADD COLUMN `audio_file_id` BIGINT NULL COMMENT '수록곡 전용 업로드 음원 ID. 가사의 음원보다 우선' AFTER `mr_youtube_video_id`,
    ADD INDEX `idx_songbook_audio_file` (`audio_file_id`),
    ADD CONSTRAINT `fk_songbook_audio` FOREIGN KEY (`audio_file_id`) REFERENCES `audio_files` (`id`) ON DELETE SET NULL;
