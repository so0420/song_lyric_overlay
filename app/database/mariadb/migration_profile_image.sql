-- ============================================
-- 프로필 사진 업로드 (users.picture_path)
-- ============================================
-- 적용 안내:
--   python migrate.py --file profile_image
--
-- 배경:
--   users.picture 는 '표시용 URL' 컬럼으로만 있었고 아무도 값을 쓰지 않았다.
--   이제 마이페이지에서 직접 올린 사진을 프로필로 쓸 수 있게 하면서,
--   파일 본체는 서버 디스크(storage/profile)에 두고 여기에는 위치만 둔다.
--
-- 왜 컬럼을 하나 더 두나:
--   picture 는 화면이 그대로 <img src> 에 넣는 값이고(교체할 때마다 경로가 바뀐다),
--   picture_path 는 파일을 지우기 위한 저장 루트 기준 상대 경로다.
--   URL 에서 경로를 되짚어 파싱하는 방식은 URL 형태를 바꾸는 순간 조용히 깨지므로
--   지울 대상은 따로 기록해 둔다.
--
-- 선행 조건: users 테이블이 있어야 한다.
-- 주의: migrate.py 의 split_statements 는 문자열 리터럴을 인식하지 못하므로
--       COMMENT 문자열 안에 세미콜론을 쓰지 말 것.
-- ============================================

ALTER TABLE `users`
    ADD COLUMN `picture_path` VARCHAR(255) NULL COMMENT '업로드한 프로필 사진의 저장 루트 기준 상대 경로 (예 ab/cd/abcd....jpg). 외부 URL 을 쓰는 경우 NULL' AFTER `picture`;
