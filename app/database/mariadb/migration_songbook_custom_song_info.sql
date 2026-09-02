-- ============================================
-- 수록곡별 곡 정보 덮어쓰기 (streamer_songbooks.custom_title / custom_artist)
-- ============================================
-- 적용 안내:
--   python migrate.py --file songbook_custom_song_info
--
-- 배경:
--   곡 제목/가수를 고치려면 지금까지 songs·artists 를 고치는 수밖에 없었고, 그건
--   서비스 전체의 곡 정보라서 관리자만 할 수 있었다. 노래책 주인이 자기 노래책에
--   보이는 표기만 바꾸고 싶은 경우(띄어쓰기, 부제 정리, 한글 표기 등)를 위해
--   수록곡에 덮어쓸 값을 둔다.
--
-- 커버(cover_image_path)와 같은 원칙이다:
--   값이 있으면 그것을, 없으면 원곡(songs.title / artists.name)을 쓴다.
--   NULL 은 '덮어쓰지 않음' 이고 빈 문자열은 쓰지 않는다 — 조회가 COALESCE 하나로
--   끝나야 해서, '비었지만 덮어쓴 상태' 같은 중간 상태를 만들지 않는다.
--   (app/database/songbook_repository.py 의 SONGBOOK_TITLE_EXPR / SONGBOOK_ARTIST_EXPR)
--
-- 길이는 원본 컬럼과 맞춘다 (songs.title / artists.name = VARCHAR(512)).
--
-- 선행 조건: streamer_songbooks 테이블이 있어야 한다.
-- 주의: migrate.py 의 split_statements 는 문자열 리터럴을 인식하지 못하므로
--       COMMENT 문자열 안에 세미콜론을 쓰지 말 것.
-- ============================================

ALTER TABLE `streamer_songbooks`
    ADD COLUMN `custom_title` VARCHAR(512) NULL COMMENT '이 노래책에서만 쓸 곡 제목. NULL 이면 songs.title 을 그대로 쓴다' AFTER `song_id`,
    ADD COLUMN `custom_artist` VARCHAR(512) NULL COMMENT '이 노래책에서만 쓸 가수 이름. NULL 이면 artists.name 을 그대로 쓴다' AFTER `custom_title`;
