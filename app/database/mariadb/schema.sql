-- -------------------------------------------------------------------------------------------------------------
-- Oauth and User
-- -------------------------------------------------------------------------------------------------------------

-- Users table: Core user information
CREATE TABLE IF NOT EXISTS `users` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '내부 고유 식별자',
    `email` VARCHAR(255) NULL UNIQUE COMMENT '사용자 이메일 (탈퇴 후 파기 시 NULL)',
    `password_hash` VARCHAR(255) NULL COMMENT '비밀번호 해시 (bcrypt) - 이메일 로그인용',
    `email_verified` TINYINT(1) DEFAULT 0 COMMENT '이메일 인증 여부 (1: 인증됨, 0: 미인증)',
    `name` VARCHAR(100) COMMENT '사용자 이름/닉네임',
    `picture` TEXT COMMENT '프로필 이미지 URL (업로드 시 /api/v1/users/profile-image/... 형태)',
    `picture_path` VARCHAR(255) NULL COMMENT '업로드한 프로필 사진의 저장 루트 기준 상대 경로. 외부 URL 을 쓰는 경우 NULL',
    `is_active` TINYINT(1) DEFAULT 1 COMMENT '활성 상태 (1: 활성, 0: 비활성)',
    `is_admin` TINYINT(1) DEFAULT 0 COMMENT '관리자 여부 (1: 관리자, 0: 일반 사용자)',
    `overlay_approved` TINYINT(1) DEFAULT 0 COMMENT '오버레이 기능 사용 승인 (1: 승인, 0: 미승인)',
    `overlay_token` VARCHAR(64) NULL UNIQUE COMMENT 'OBS 오버레이용 영구 토큰',
    `last_login` TIMESTAMP NULL COMMENT '최근 로그인 일시',
    `ip` VARCHAR(45) COMMENT '최근 로그인 IP',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '가입 일시',
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '정보 수정 일시',
    `deleted_at` TIMESTAMP NULL COMMENT '삭제 일시 (소프트 삭제)',
    `purged_at` TIMESTAMP NULL COMMENT '탈퇴 후 개인정보 파기 완료 일시',

    INDEX `idx_users_purge_target` (`purged_at`, `deleted_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Social Accounts table: Support multiple OAuth providers (Google, Naver, etc.)
CREATE TABLE IF NOT EXISTS `social_accounts` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `user_id` BIGINT NOT NULL COMMENT 'users 테이블 참조 ID',
    `provider` VARCHAR(50) NOT NULL COMMENT 'OAuth 제공자 (google, naver, etc.)',
    `provider_user_id` VARCHAR(255) NOT NULL COMMENT 'OAuth 제공자에서 부여한 고유 UID',
    `provider_email` VARCHAR(255) COMMENT 'OAuth 제공자에서 받은 이메일',
    `provider_name` VARCHAR(100) COMMENT 'OAuth 제공자에서 받은 이름',
    `provider_picture` TEXT COMMENT 'OAuth 제공자에서 받은 프로필 이미지 URL',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- 외래 키 설정: 사용자가 삭제되면 연관된 소셜 계정 정보도 삭제
    CONSTRAINT `fk_social_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,

    -- 동일한 제공자에서는 유일한 고유 대상이어야 함
    UNIQUE KEY `unique_provider_user` (`provider`, `provider_user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 인덱스 추가 (조회 성능 최적화)
CREATE INDEX `idx_social_provider_email` ON `social_accounts`(`provider_email`);
CREATE INDEX `idx_user_email` ON `users`(`email`);
CREATE INDEX `idx_social_user_id` ON `social_accounts`(`user_id`);

-- -------------------------------------------------------------------------------------------------------------
-- Music
-- -------------------------------------------------------------------------------------------------------------

-- Artists table: 가수 정보
CREATE TABLE IF NOT EXISTS `artists` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `name` VARCHAR(255) NOT NULL COMMENT '가수 이름',
    `artist_external_id` VARCHAR(255) NOT NULL COMMENT '가수 ID - custom_{uuid}',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- 유니크 키 설정: 가수는 하나만
    UNIQUE KEY `unique_artist_external_id` (`artist_external_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Songs table: 음악 정보
CREATE TABLE IF NOT EXISTS `songs` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `title` VARCHAR(255) NOT NULL COMMENT '노래 제목',
    `song_external_id` VARCHAR(255) NULL COMMENT '노래 ID - custom_{uuid}',
    `artist_id` BIGINT NULL COMMENT '아티스트 ID',
    `official_youtube_video_id` VARCHAR(255) NULL COMMENT '노래 기본 유튜브 영상 ID: mr 말고 공식 노래꺼 / 없으면 null',
    `cover_image_url` TEXT NULL COMMENT '노래 커버 이미지 URL. 저장은 하지만 사용하지 않음.(저작권 이슈)',
    `length_ms` INT NULL COMMENT '음악 길이 (밀리초)',
    `owner_id` BIGINT NULL COMMENT '소유자 ID - 노래를 등록한 사람 정보. null이면 관리자가 등록한 노래. / 커스텀 노래를 위한 곳',
    `is_public` TINYINT(1) DEFAULT 1 COMMENT '공개 여부 (1: 공개, 0: 비공개)',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- 유니크 키 설정: 노래는 하나만
    UNIQUE KEY `unique_song_external_id` (`song_external_id`),

    -- 외래 키 설정: 소유자 삭제 시 NULL로 변경
    CONSTRAINT `fk_song_owner` FOREIGN KEY (`owner_id`) REFERENCES `users` (`id`) ON DELETE SET NULL,
    -- 외래 키 설정: 아티스트 삭제 시 NULL로 변경
    CONSTRAINT `fk_song_artist` FOREIGN KEY (`artist_id`) REFERENCES `artists` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- Audio files: 이용자가 업로드한 음원 (가사 재생 소스, 유튜브 MR 의 대안)
--   파일 본체는 서버 디스크(storage/audio)에 두고 여기에는 위치와 메타데이터만 둔다.
--   공개 범위는 이 테이블이 갖지 않고, 연결된 가사(song_lyrics.visibility)를 따른다.
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

    -- 외래 키 설정: 소유자 삭제 시 NULL로 변경
    CONSTRAINT `fk_audio_owner` FOREIGN KEY (`owner_id`) REFERENCES `users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- Song lyrics: 노래 가사
CREATE TABLE IF NOT EXISTS `song_lyrics` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `owner_id` BIGINT NULL COMMENT '소유자 ID - 가사 등록한 사람 정보. null이면 관리자가 등록한 가사.',
    `song_id` BIGINT NOT NULL COMMENT '노래 ID',
    `title` VARCHAR(255) NULL COMMENT '가사 제목 (예: 정식 싱크, 숏츠용 등)',
    `mr_youtube_video_id` VARCHAR(255) NULL COMMENT '음악 영상 ID: mr영상꺼',
    `audio_file_id` BIGINT NULL COMMENT '업로드 음원 ID. mr_youtube_video_id 와 택일',
    `lyrics_data` TEXT NULL COMMENT '노래 가사: [{"start": 0, "end": 1000, "text": "가사"}] 형식',
    `is_verified` TINYINT(1) DEFAULT 0 COMMENT '가사 검증 여부 (1: 검증됨, 0: 검증되지 않음)',
    `visibility` ENUM('public','private','whitelist') NOT NULL DEFAULT 'public' COMMENT '공개 범위: public=전체공개, private=본인+관리자, whitelist=본인+관리자+허용된 유저',
    `likes_count` INT DEFAULT 0 COMMENT '좋아요 수',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    `deleted_at` TIMESTAMP NULL COMMENT '삭제 일시 (소프트 삭제)',

    INDEX `idx_lyrics_audio_file` (`audio_file_id`),

    -- 외래 키 설정: 소유자 삭제 시 NULL로 변경
    CONSTRAINT `fk_lyrics_owner` FOREIGN KEY (`owner_id`) REFERENCES `users` (`id`) ON DELETE SET NULL,
    -- 외래 키 설정: 노래 삭제 시 삭제
    CONSTRAINT `fk_lyrics_song` FOREIGN KEY (`song_id`) REFERENCES `songs` (`id`) ON DELETE CASCADE,
    -- 외래 키 설정: 음원 파일 삭제 시 NULL로 변경
    CONSTRAINT `fk_lyrics_audio` FOREIGN KEY (`audio_file_id`) REFERENCES `audio_files` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Lyrics whitelist: visibility='whitelist'인 가사에 대해 허용된 유저 목록
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

-- -------------------------------------------------------------------------------------------------------------
-- User Lyrics Favorites
-- -------------------------------------------------------------------------------------------------------------

-- User Lyrics Favorites table: 사용자 가사 즐겨찾기
CREATE TABLE IF NOT EXISTS `user_lyrics_favorites` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `user_id` BIGINT NOT NULL COMMENT 'users 테이블 참조 ID',
    `lyrics_id` BIGINT NOT NULL COMMENT 'song_lyrics 테이블 참조 ID',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- 유니크 키 설정: 같은 가사를 중복 즐겨찾기 불가
    UNIQUE KEY `unique_user_lyrics` (`user_id`, `lyrics_id`),

    -- 외래 키 설정: 사용자 삭제 시 연관된 즐겨찾기도 삭제
    CONSTRAINT `fk_favorite_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,
    -- 외래 키 설정: 가사 삭제 시 연관된 즐겨찾기도 삭제
    CONSTRAINT `fk_favorite_lyrics` FOREIGN KEY (`lyrics_id`) REFERENCES `song_lyrics` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -------------------------------------------------------------------------------------------------------------
-- User Overlay Settings
-- -------------------------------------------------------------------------------------------------------------

-- User Overlay Settings table: 사용자 오버레이 설정
CREATE TABLE IF NOT EXISTS `user_overlay_settings` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `user_id` BIGINT NOT NULL COMMENT 'users 테이블 참조 ID',
    `settings_json` TEXT NOT NULL COMMENT '오버레이 설정 JSON',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- 유니크 키 설정: 사용자당 하나의 설정만
    UNIQUE KEY `unique_user_overlay` (`user_id`),

    -- 외래 키 설정: 사용자 삭제 시 연관된 설정도 삭제
    CONSTRAINT `fk_overlay_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_songs_artist_id ON songs(artist_id);
CREATE INDEX idx_songs_owner_id ON songs(owner_id);
CREATE INDEX idx_songs_title_artist ON songs(title, artist_id);  -- 같은 제목+가수 묶기(중복 곡 정규화)
CREATE INDEX idx_lyrics_song_id ON song_lyrics(song_id);
CREATE INDEX idx_lyrics_owner_id ON song_lyrics(owner_id);
CREATE INDEX idx_lyrics_visibility ON song_lyrics(visibility);
CREATE INDEX idx_wl_user_id ON lyrics_whitelist(user_id);
CREATE INDEX idx_favorites_user_id ON user_lyrics_favorites(user_id);
CREATE INDEX idx_favorites_lyrics_id ON user_lyrics_favorites(lyrics_id);
CREATE INDEX idx_overlay_user_id ON user_overlay_settings(user_id);

-- -------------------------------------------------------------------------------------------------------------
-- User Overlay Presets
-- -------------------------------------------------------------------------------------------------------------

-- User Overlay Presets table: 사용자 오버레이 프리셋
CREATE TABLE IF NOT EXISTS `user_overlay_presets` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `user_id` BIGINT NOT NULL COMMENT 'users 테이블 참조 ID',
    `name` VARCHAR(100) NOT NULL COMMENT '프리셋 이름',
    `settings_json` TEXT NOT NULL COMMENT '오버레이 설정 JSON',
    `is_active` TINYINT(1) DEFAULT 0 COMMENT '현재 활성화된 프리셋 여부',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- 외래 키 설정: 사용자 삭제 시 연관된 프리셋도 삭제
    CONSTRAINT `fk_preset_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_preset_user_id ON user_overlay_presets(user_id);

-- -------------------------------------------------------------------------------------------------------------
-- User Playlist (노래하기 재생목록 — 시청자 노래책 페이지/오버레이에서 조회)
-- -------------------------------------------------------------------------------------------------------------

-- 사용자별 재생목록 (한 행). playlist_json 은 [{lyricsId, songId, songTitle, artistName, videoId, coverImageUrl, ...}]
CREATE TABLE IF NOT EXISTS `user_playlists` (
    `user_id` BIGINT NOT NULL PRIMARY KEY COMMENT 'users 테이블 참조 ID',
    `playlist_json` TEXT NOT NULL COMMENT '재생목록 JSON 배열',
    `current_index` INT NOT NULL DEFAULT -1 COMMENT '현재 재생 중 인덱스 (-1=없음)',
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- 외래 키 설정: 사용자 삭제 시 재생목록도 삭제
    CONSTRAINT `fk_playlist_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -------------------------------------------------------------------------------------------------------------
-- Overlay Access Requests
-- -------------------------------------------------------------------------------------------------------------

-- 오버레이 기능 사용 요청 테이블
CREATE TABLE IF NOT EXISTS `overlay_access_requests` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `user_id` BIGINT NOT NULL COMMENT 'users 테이블 참조 ID',
    `platform_url` VARCHAR(500) NOT NULL COMMENT '방송 플랫폼 주소',
    `message` TEXT NULL COMMENT '추가 메시지 (최대 1500자)',
    `status` ENUM('pending', 'approved', 'rejected', 'revoked') DEFAULT 'pending' COMMENT '요청 상태',
    `rejection_reason` TEXT NULL COMMENT '거절/회수 사유',
    `reviewed_by` BIGINT NULL COMMENT '검토한 관리자 ID',
    `reviewed_at` TIMESTAMP NULL COMMENT '검토 일시',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- 외래 키 설정
    CONSTRAINT `fk_access_request_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_access_request_reviewer` FOREIGN KEY (`reviewed_by`) REFERENCES `users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_access_request_user_id ON overlay_access_requests(user_id);
CREATE INDEX idx_access_request_status ON overlay_access_requests(status);

-- -------------------------------------------------------------------------------------------------------------
-- User Lyrics Memos (개인 메모)
-- -------------------------------------------------------------------------------------------------------------

-- 사용자 가사별 개인 메모 테이블 (노래 키 정보 등 개인 참고용)
CREATE TABLE IF NOT EXISTS `user_lyrics_memos` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `user_id` BIGINT NOT NULL COMMENT 'users 테이블 참조 ID',
    `lyrics_id` BIGINT NOT NULL COMMENT 'song_lyrics 테이블 참조 ID',
    `memo` TEXT NOT NULL COMMENT '메모 내용',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- 유니크 키 설정: 같은 가사에 사용자당 하나의 메모만
    UNIQUE KEY `unique_user_lyrics_memo` (`user_id`, `lyrics_id`),

    -- 외래 키 설정
    CONSTRAINT `fk_memo_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_memo_lyrics` FOREIGN KEY (`lyrics_id`) REFERENCES `song_lyrics` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_memo_user_id ON user_lyrics_memos(user_id);
CREATE INDEX idx_memo_lyrics_id ON user_lyrics_memos(lyrics_id);

-- -------------------------------------------------------------------------------------------------------------
-- Audit Logs
-- -------------------------------------------------------------------------------------------------------------

-- 관리자 활동 로그 테이블
CREATE TABLE IF NOT EXISTS `audit_logs` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `actor_id` BIGINT NOT NULL COMMENT '작업 수행자 ID',
    `action` VARCHAR(100) NOT NULL COMMENT '수행한 작업 (approve_access, revoke_access, etc.)',
    `target_type` VARCHAR(50) NULL COMMENT '대상 유형 (user, lyrics, etc.)',
    `target_id` BIGINT NULL COMMENT '대상 ID',
    `details` JSON NULL COMMENT '추가 상세 정보 (JSON)',
    `ip_address` VARCHAR(45) NULL COMMENT '요청 IP',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- 외래 키 설정: 수행자 삭제 시 NULL로 변경하지 않고 기록 유지
    CONSTRAINT `fk_audit_actor` FOREIGN KEY (`actor_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_audit_actor_id ON audit_logs(actor_id);
CREATE INDEX idx_audit_action ON audit_logs(action);
CREATE INDEX idx_audit_created_at ON audit_logs(created_at);

-- ============================================
-- 노래책 (Songbook) 기능
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
    `audio_file_id` BIGINT NULL COMMENT '수록곡 전용 업로드 음원 ID. 가사의 음원보다 우선',
    `lyrics_id` BIGINT NULL COMMENT '연결된 가사 ID (song_lyrics)',
    `cover_image_url` TEXT NULL COMMENT '커버 이미지 URL',
    `tags` TEXT NOT NULL DEFAULT '[]' COMMENT '노래 태그 JSON ["tag1", ...] (streamers.tags의 name과 연결)',
    `difficulty` TINYINT NULL COMMENT '난이도 (1 ~ 10), NULL=미설정',
    `memo` VARCHAR(255) NULL COMMENT '노래 설명/메모',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY `unique_streamer_song` (`streamer_id`, `song_id`),
    INDEX `idx_songbook_streamer_sort` (`streamer_id`, `sort_order`),
    INDEX `idx_songbook_song_id` (`song_id`),
    INDEX `idx_songbook_audio_file` (`audio_file_id`),
    CONSTRAINT `fk_songbook_streamer` FOREIGN KEY (`streamer_id`) REFERENCES `streamers` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_songbook_song` FOREIGN KEY (`song_id`) REFERENCES `songs` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_songbook_lyrics` FOREIGN KEY (`lyrics_id`) REFERENCES `song_lyrics` (`id`) ON DELETE SET NULL,
    CONSTRAINT `fk_songbook_audio` FOREIGN KEY (`audio_file_id`) REFERENCES `audio_files` (`id`) ON DELETE SET NULL
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

-- 노래 신청 이력 로그 (통계 전용, append-only)
-- song_requests 는 신청 큐라서 '이미 부름' 정리/전체 삭제로 물리 삭제된다.
-- 최근 N일 신청 횟수 같은 통계는 삭제에 영향받지 않도록 이 로그에 영구 적재한다.
-- (곡이 특정되는 신청만 기록 — song_id NOT NULL)
CREATE TABLE IF NOT EXISTS `song_request_logs` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `streamer_id` BIGINT NOT NULL COMMENT 'streamers 테이블 참조 ID',
    `song_id` BIGINT NOT NULL COMMENT 'songs 테이블 참조 ID',
    `requested_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '신청 시각',
    INDEX `idx_reqlog_streamer_song_time` (`streamer_id`, `song_id`, `requested_at`),
    CONSTRAINT `fk_reqlog_streamer` FOREIGN KEY (`streamer_id`) REFERENCES `streamers` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_reqlog_song` FOREIGN KEY (`song_id`) REFERENCES `songs` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================
-- 치지직(Chzzk) 연동 — 유저별 채널 uid 매핑 (OAuth/토큰은 jamkubot 위임)
-- ============================================
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

-- ============================================
-- 노래 타임라인 기록
-- ============================================
-- 치지직 연동 유저가 방송 중 부른 곡을 방송 시작(openDate) 기준 경과 시간과 함께 기록.
-- 방송별로 openDate 로 묶어 조회하며, 최근 1달치만 보관한다.
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
