-- -------------------------------------------------------------------------------------------------------------
-- Oauth and User
-- -------------------------------------------------------------------------------------------------------------

-- Users table: Core user information
CREATE TABLE IF NOT EXISTS `users` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '내부 고유 식별자',
    `email` VARCHAR(255) NOT NULL UNIQUE COMMENT '사용자 이메일',
    `name` VARCHAR(100) COMMENT '사용자 이름/닉네임',
    `picture` TEXT COMMENT '프로필 이미지 URL',
    `is_active` TINYINT(1) DEFAULT 1 COMMENT '활성 상태 (1: 활성, 0: 비활성)',
    `is_admin` TINYINT(1) DEFAULT 0 COMMENT '관리자 여부 (1: 관리자, 0: 일반 사용자)',
    `last_login` TIMESTAMP NULL COMMENT '최근 로그인 일시',
    `ip` VARCHAR(45) COMMENT '최근 로그인 IP',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '가입 일시',
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '정보 수정 일시'
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

-- Chzzk 앱 정보
CREATE TABLE IF NOT EXISTS `chzzk_app_config` (
    `id` int auto_increment primary key,
    `app_id` varchar(50) not null,
    `app_name` varchar(30) null,
    `client_id` varchar(50) not null,
    `client_secret` varchar(50) not null,
    `redirect_uri` varchar(100) not null
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

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
    
    -- 외래 키 설정: 소유자 삭제 시 NULL로 변경
    CONSTRAINT `fk_lyrics_owner` FOREIGN KEY (`owner_id`) REFERENCES `users` (`id`) ON DELETE SET NULL,
    -- 외래 키 설정: 노래 삭제 시 삭제
    CONSTRAINT `fk_lyrics_song` FOREIGN KEY (`song_id`) REFERENCES `songs` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -------------------------------------------------------------------------------------------------------------
-- Music
-- -------------------------------------------------------------------------------------------------------------

-- Streamers table: 스트리머 설정값
CREATE TABLE IF NOT EXISTS `streamers` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `user_id` BIGINT NOT NULL COMMENT 'users 테이블 참조 ID',
    `streamer_id` VARCHAR(255) NOT NULL UNIQUE COMMENT '외부에 노출될 스트리머 ID',
    `slug` VARCHAR(100) NOT NULL UNIQUE COMMENT '스트리머 고유 식별 주소 (URL slug)',
    `token` VARCHAR(255) UNIQUE COMMENT '고유 보안 토큰',
    `description` TEXT NULL COMMENT '스트리머 설명',
    `social_links` TEXT NOT NULL DEFAULT '[]' COMMENT '스트리머 소셜 링크 JSON', -- [{"name": "youtube", "url": "https://www.youtube.com/"}]
    `tags` TEXT NOT NULL DEFAULT '[]' COMMENT '스트리머가 만든 노래 태그 목록 JSON. 주로 카테고리 등 저장.', -- [{"name": "tag1", "color": "#FF0000"}]
    `request_enabled` TINYINT(1) DEFAULT 0 COMMENT '신청 기능 전체 on/off',
    `request_chat_enabled` TINYINT(1) DEFAULT 0 COMMENT '채팅 신청 on/off',
    `request_donation_enabled` TINYINT(1) DEFAULT 0 COMMENT '후원 신청 on/off',
    `request_web_enabled` TINYINT(1) DEFAULT 0 COMMENT '홈페이지 신청 on/off',
    `default_price_cheese` INT DEFAULT 0 COMMENT '기본 노래 신청 치즈 가격',
    `default_price_balloon` INT DEFAULT 0 COMMENT '기본 노래 신청 별풍선 가격',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- 유니크 키 설정
    UNIQUE KEY `unique_user_id` (`user_id`),
    UNIQUE KEY `unique_streamer_id` (`streamer_id`),
    -- 슬러그 인덱스
    INDEX `idx_streamer_slug` (`slug`),
    
    -- 외래 키 설정: 사용자가 삭제되면 연관된 스트리머 정보도 삭제
    CONSTRAINT `fk_streamer_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Streamer songbooks table: 스트리머의 노래책 노래목록
CREATE TABLE IF NOT EXISTS `streamer_songbooks` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `streamer_id` BIGINT NOT NULL COMMENT '스트리머 ID',
    `sort_order` INT NOT NULL COMMENT '스트리머 지정 노래 순서',
    `song_id` BIGINT NOT NULL COMMENT '노래 ID',
    `mr_youtube_video_id` VARCHAR(255) NULL COMMENT '음악 영상 ID: mr영상꺼',
    `lyrics_id` BIGINT NULL COMMENT '가사 ID',
    `cover_image_url` TEXT NULL COMMENT '커버 이미지 URL',
    `tags` TEXT NOT NULL DEFAULT '[]' COMMENT '스트리머 지정 노래 태그.', -- streamers.tags의 name과 연결됨. ['tag1', 'tag2',...]
    `difficulty` TINYINT NOT NULL COMMENT '스트리머 지정 노래 난이도 (1 ~ 10)',
    `price_cheese` INT DEFAULT 0 COMMENT '신청에 필요한 치즈 개수',
    `price_balloon` INT DEFAULT 0 COMMENT '신청에 필요한 별풍선 개수',
    `memo` VARCHAR(255) NULL COMMENT '스트리머 지정 노래 설명/메모',
    `design` TEXT NULL COMMENT '스트리머 지정 노래 디자인 데이터',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    -- 유니크 키 설정: 스트리머와 노래는 유니크해야함.
    UNIQUE KEY `unique_streamer_song` (`streamer_id`, `song_id`),
    -- 정렬용 인덱스 (유니크 제약은 순서 변경 시 불편하므로 제거)
    INDEX `idx_streamer_sort` (`streamer_id`, `sort_order`),

    -- 외래 키 설정: 스트리머 삭제 시 연관된 노래책도 삭제
    CONSTRAINT `fk_sb_streamer` FOREIGN KEY (`streamer_id`) REFERENCES `streamers` (`id`) ON DELETE CASCADE,
    -- 외래 키 설정: 노래 삭제 시 연관된 노래도 삭제
    CONSTRAINT `fk_sb_song` FOREIGN KEY (`song_id`) REFERENCES `songs` (`id`) ON DELETE CASCADE,
    -- 외래 키 설정: 가사 삭제 시 가사 정보 null로 변경
    CONSTRAINT `fk_sb_lyrics` FOREIGN KEY (`lyrics_id`) REFERENCES `song_lyrics` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -------------------------------------------------------------------------------------------------------------
-- Users
-- -------------------------------------------------------------------------------------------------------------

-- Follows table: 스트리머 팔로우 정보를 저장
CREATE TABLE IF NOT EXISTS `follows` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `user_id` BIGINT NOT NULL COMMENT '유저 ID',
    `streamer_id` BIGINT NOT NULL COMMENT '스트리머 ID',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY `unique_user_streamer` (`user_id`, `streamer_id`),
    
    -- 외래 키 설정: 유저 삭제 시 연관된 팔로우도 삭제
    CONSTRAINT `fk_follow_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,
    -- 외래 키 설정: 스트리머 삭제 시 연관된 팔로우도 삭제
    CONSTRAINT `fk_follow_streamer` FOREIGN KEY (`streamer_id`) REFERENCES `streamers` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;



CREATE INDEX idx_songs_artist_id ON songs(artist_id);
CREATE INDEX idx_songs_owner_id ON songs(owner_id);
CREATE INDEX idx_lyrics_song_id ON song_lyrics(song_id);
CREATE INDEX idx_lyrics_owner_id ON song_lyrics(owner_id);
CREATE INDEX idx_sb_song_id ON streamer_songbooks(song_id);
CREATE INDEX idx_follows_streamer_id ON follows(streamer_id);

-- -------------------------------------------------------------------------------------------------------------
-- Contact Inquiries
-- -------------------------------------------------------------------------------------------------------------

-- Contact Inquiries table: 문의하기
CREATE TABLE IF NOT EXISTS `contact_inquiries` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `user_id` BIGINT NULL COMMENT '로그인한 유저 ID (비로그인 시 NULL)',
    `name` VARCHAR(100) NOT NULL COMMENT '문의자 이름',
    `email` VARCHAR(255) NOT NULL COMMENT '문의자 이메일',
    `subject` VARCHAR(255) NOT NULL COMMENT '문의 제목',
    `message` TEXT NOT NULL COMMENT '문의 내용',
    `status` ENUM('pending', 'in_progress', 'resolved', 'closed') DEFAULT 'pending' COMMENT '처리 상태',
    `admin_reply` TEXT NULL COMMENT '관리자 답변',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    -- 외래 키 설정: 유저 삭제 시 NULL로 변경
    CONSTRAINT `fk_inquiry_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_inquiry_user_id ON contact_inquiries(user_id);
CREATE INDEX idx_inquiry_status ON contact_inquiries(status);

-- -------------------------------------------------------------------------------------------------------------
-- Notices (공지사항)
-- -------------------------------------------------------------------------------------------------------------

-- Notices table: 공지사항
CREATE TABLE IF NOT EXISTS `notices` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `title` VARCHAR(255) NOT NULL COMMENT '공지 제목',
    `content` TEXT NOT NULL COMMENT '공지 내용',
    `is_pinned` TINYINT(1) DEFAULT 0 COMMENT '고정 여부 (1: 고정, 0: 일반)',
    `is_published` TINYINT(1) DEFAULT 1 COMMENT '게시 여부 (1: 게시, 0: 비게시)',
    `view_count` INT DEFAULT 0 COMMENT '조회수',
    `author_id` BIGINT NULL COMMENT '작성자 ID',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    -- 외래 키 설정: 작성자 삭제 시 NULL로 변경
    CONSTRAINT `fk_notice_author` FOREIGN KEY (`author_id`) REFERENCES `users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_notice_pinned ON notices(is_pinned);
CREATE INDEX idx_notice_published ON notices(is_published);
CREATE INDEX idx_notice_created_at ON notices(created_at);
CREATE FULLTEXT INDEX idx_notice_search ON notices(title, content);

-- -------------------------------------------------------------------------------------------------------------
-- Chzzk Integration
-- -------------------------------------------------------------------------------------------------------------

-- User Chzzk Tokens table: store OAuth tokens for users, linked to specific Chzzk apps.
CREATE TABLE IF NOT EXISTS `user_chzzk_tokens` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `user_id` BIGINT NOT NULL COMMENT 'users 테이블 참조 ID',
    `app_id` VARCHAR(50) NOT NULL COMMENT 'chzzk_app_config 테이블의 app_id',
    `channel_id` VARCHAR(100) NOT NULL COMMENT '치지직 채널 ID (UID)',
    `channel_name` VARCHAR(100) COMMENT '치지직 채널 이름',
    `access_token` TEXT NOT NULL,
    `refresh_token` TEXT NOT NULL,
    `expires_at` BIGINT NOT NULL COMMENT '토큰 만료 일시 (Unix Timestamp)',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    CONSTRAINT `fk_chzzk_token_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,
    UNIQUE KEY `unique_user_app` (`user_id`, `app_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;



-- -------------------------------------------------------------------------------------------------------------
-- Song Request
-- -------------------------------------------------------------------------------------------------------------

-- Song Request table: store song requests from users.
CREATE TABLE IF NOT EXISTS `song_requests` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `streamer_id` BIGINT NOT NULL COMMENT 'streamers 테이블 참조 ID',
    `requester` VARCHAR(255) NOT NULL COMMENT '신청자 닉네임',
    `requester_type` ENUM('CHAT', 'DONATION', 'WEB', 'MANUAL') NOT NULL COMMENT '신청 경로',
    `requester_platform` VARCHAR(50) NULL COMMENT '신청자 플랫폼: CHZZK, YOUTUBE, SOOP 등',
    `sort_order` INT NOT NULL COMMENT '신청 순서',
    `status` ENUM('waiting', 'playing', 'done') DEFAULT 'waiting' COMMENT '상태: 대기중/부르는중/이미부름',
    `song_id` BIGINT NULL COMMENT 'songs 테이블 참조 ID',
    `title` VARCHAR(255) NULL COMMENT '노래 제목 - 노래 제목이 없을 경우 NULL', -- 노래책에 없는 노래를 신청했을 경우 임시 노래로 넣기 위함.
    `artist` VARCHAR(255) NULL COMMENT '노래 아티스트 - 노래 아티스트가 없을 경우 NULL', -- 노래책에 없는 노래를 신청했을 경우 임시 노래로 넣기 위함.
    `request_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    CONSTRAINT `fk_song_request_streamer` FOREIGN KEY (`streamer_id`) REFERENCES `streamers` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_song_request_song` FOREIGN KEY (`song_id`) REFERENCES `songs` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_song_request_streamer_id ON song_requests(streamer_id);
CREATE INDEX idx_song_request_sort_order ON song_requests(sort_order);
CREATE INDEX idx_song_request_status ON song_requests(status);
