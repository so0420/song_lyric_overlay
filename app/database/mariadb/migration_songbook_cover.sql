-- ============================================
-- 노래책 수록곡 커버 이미지 업로드 (streamer_songbooks.cover_image_path)
-- ============================================
-- 적용 안내:
--   python migrate.py --file songbook_cover
--
-- 배경:
--   수록곡 커버는 지금까지 cover_image_url(외부 http(s) 주소)로만 지정할 수 있었다.
--   이제 이용자가 이미지를 직접 올릴 수 있게 하면서, 파일 본체는 서버 디스크
--   (storage/cover)에 두고 여기에는 위치만 둔다.
--
-- 왜 컬럼을 하나 더 두나:
--   users.picture / users.picture_path 와 같은 이유다. cover_image_url 은
--   화면이 그대로 <img src> 에 넣는 값이고, cover_image_path 는 파일을 지우기 위한
--   저장 루트 기준 상대 경로다. URL 에서 경로를 되짚어 파싱하는 방식은 URL 형태를
--   바꾸는 순간 조용히 깨지므로 지울 대상은 따로 기록해 둔다.
--   컬럼을 나눠 두면 업로드 커버와 URL 커버가 서로를 덮어쓰지 않는다 — 수록곡 수정
--   화면이 매번 cover_image_url 을 함께 보내기 때문에 이게 중요하다.
--
-- 커버 해석 순서(조회 시): 업로드 커버 > 수록곡 지정 URL > 곡 자체 커버
--   (app/database/songbook_repository.py 의 SONGBOOK_COVER_EXPR)
--
-- 선행 조건: streamer_songbooks 테이블이 있어야 한다.
-- 주의: migrate.py 의 split_statements 는 문자열 리터럴을 인식하지 못하므로
--       COMMENT 문자열 안에 세미콜론을 쓰지 말 것.
-- ============================================

ALTER TABLE `streamer_songbooks`
    ADD COLUMN `cover_image_path` VARCHAR(255) NULL COMMENT '업로드한 커버 이미지의 저장 루트 기준 상대 경로 (예 ab/cd/abcd....jpg). 업로드 커버가 없으면 NULL' AFTER `cover_image_url`;
