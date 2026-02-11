-- -------------------------------------------------------------------------------------------------------------
-- Oauth and User
-- -------------------------------------------------------------------------------------------------------------

-- Users table: Core user information
CREATE TABLE IF NOT EXISTS `users` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '내부 고유 식별자',
    `email` VARCHAR(255) NOT NULL UNIQUE COMMENT '사용자 이메일',
    `password_hash` VARCHAR(255) NULL COMMENT '비밀번호 해시 (bcrypt) - 이메일 로그인용',
    `email_verified` TINYINT(1) DEFAULT 0 COMMENT '이메일 인증 여부 (1: 인증됨, 0: 미인증)',
    `name` VARCHAR(100) COMMENT '사용자 이름/닉네임',
    `picture` TEXT COMMENT '프로필 이미지 URL',
    `is_active` TINYINT(1) DEFAULT 1 COMMENT '활성 상태 (1: 활성, 0: 비활성)',
    `is_admin` TINYINT(1) DEFAULT 0 COMMENT '관리자 여부 (1: 관리자, 0: 일반 사용자)',
    `last_login` TIMESTAMP NULL COMMENT '최근 로그인 일시',
    `ip` VARCHAR(45) COMMENT '최근 로그인 IP',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '가입 일시',
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '정보 수정 일시',
    `deleted_at` TIMESTAMP NULL COMMENT '삭제 일시 (소프트 삭제)'
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
    `artist_external_id` VARCHAR(255) NOT NULL COMMENT '가수 ID - 외부 서비스(itunes(줄여서 it) 등)it_id or custom_{id}',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- 유니크 키 설정: 가수는 하나만
    UNIQUE KEY `unique_artist_external_id` (`artist_external_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Songs table: 음악 정보
CREATE TABLE IF NOT EXISTS `songs` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `title` VARCHAR(255) NOT NULL COMMENT '노래 제목',
    `song_external_id` VARCHAR(255) NULL COMMENT '노래 ID - 외부 서비스(itunes(줄여서 it) 등)it_id or custom_{id}',
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


-- Song lyrics: 노래 가사
CREATE TABLE IF NOT EXISTS `song_lyrics` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `owner_id` BIGINT NULL COMMENT '소유자 ID - 가사 등록한 사람 정보. null이면 관리자가 등록한 가사.',
    `song_id` BIGINT NOT NULL COMMENT '노래 ID',
    `title` VARCHAR(255) NULL COMMENT '가사 제목 (예: 정식 싱크, 숏츠용 등)',
    `mr_youtube_video_id` VARCHAR(255) NULL COMMENT '음악 영상 ID: mr영상꺼',
    `lyrics_data` TEXT NULL COMMENT '노래 가사: [{"start": 0, "end": 1000, "text": "가사"}] 형식',
    `is_verified` TINYINT(1) DEFAULT 0 COMMENT '가사 검증 여부 (1: 검증됨, 0: 검증되지 않음)',
    `is_public` TINYINT(1) DEFAULT 1 COMMENT '공개 여부 (1: 공개, 0: 비공개)',
    `likes_count` INT DEFAULT 0 COMMENT '좋아요 수',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    `deleted_at` TIMESTAMP NULL COMMENT '삭제 일시 (소프트 삭제)',

    -- 외래 키 설정: 소유자 삭제 시 NULL로 변경
    CONSTRAINT `fk_lyrics_owner` FOREIGN KEY (`owner_id`) REFERENCES `users` (`id`) ON DELETE SET NULL,
    -- 외래 키 설정: 노래 삭제 시 삭제
    CONSTRAINT `fk_lyrics_song` FOREIGN KEY (`song_id`) REFERENCES `songs` (`id`) ON DELETE CASCADE
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
CREATE INDEX idx_lyrics_song_id ON song_lyrics(song_id);
CREATE INDEX idx_lyrics_owner_id ON song_lyrics(owner_id);
CREATE INDEX idx_favorites_user_id ON user_lyrics_favorites(user_id);
CREATE INDEX idx_favorites_lyrics_id ON user_lyrics_favorites(lyrics_id);
CREATE INDEX idx_overlay_user_id ON user_overlay_settings(user_id);
