-- ============================================
-- 곡 제목 / 가수 이름 길이 확장 (255 -> 512)
-- ============================================
-- 적용 안내:
--   python migrate.py --file song_title_length
--
-- 배경:
--   iTunes 검색 결과를 커스텀 곡으로 등록할 때 일부 곡에서 등록이 통째로 실패했다.
--     iTunes result registration error: (1406, "Data too long for column 'name' at row 1")
--   합작/컴필레이션 곡은 아티스트 표기에 참여자가 모두 나열돼 255자를 넘는 경우가 있고,
--   클래식·부제·리믹스 표기가 붙은 곡 제목도 마찬가지다.
--   INSERT 가 실패하면 그 곡은 검색 결과에서 조용히 빠지므로 컬럼을 512자로 넓힌다.
--
-- 함께 넓히는 컬럼:
--   songs.title / artists.name 의 값이 그대로 복사돼 들어가는 곳들도 같이 넓힌다.
--   여기만 255 로 남겨두면 곡 등록은 되는데 신청/타임라인 기록에서 같은 에러가 난다.
--     song_requests.title / song_requests.artist  (노래책 외 신청 — 치지직 검색 결과가 그대로 들어옴)
--     singing_timeline_records.title              (기록 시점의 곡 제목 사본)
--
-- 인덱스 주의:
--   songs 에는 idx_songs_title_artist (title, artist_id) 인덱스가 있다.
--   utf8mb4 기준 512자 = 2048 바이트로 InnoDB DYNAMIC 행 포맷의 키 상한(3072 바이트) 안이다.
--   (기존 255자도 1020 바이트라 767 바이트 상한을 이미 넘으므로 DYNAMIC 이 전제되어 있다.)
--
-- 주의: migrate.py 의 split_statements 는 문자열 리터럴을 인식하지 못하므로
--       COMMENT 문자열 안에 세미콜론을 쓰지 말 것.
-- ============================================

ALTER TABLE `artists`
    MODIFY COLUMN `name` VARCHAR(512) NOT NULL COMMENT '가수 이름';

ALTER TABLE `songs`
    MODIFY COLUMN `title` VARCHAR(512) NOT NULL COMMENT '노래 제목';

ALTER TABLE `song_requests`
    MODIFY COLUMN `title` VARCHAR(512) NULL COMMENT '노래 제목 (노래책 외 신청용)',
    MODIFY COLUMN `artist` VARCHAR(512) NULL COMMENT '아티스트 (노래책 외 신청용)';

ALTER TABLE `singing_timeline_records`
    MODIFY COLUMN `title` VARCHAR(512) NOT NULL COMMENT '기록 시점의 곡 제목 (커스텀 편집 가능)';
