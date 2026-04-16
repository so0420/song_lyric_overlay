-- iTunes 제거 마이그레이션
-- 기존 it_ 프리픽스 데이터를 custom_ 프리픽스로 변환
-- 실행 전 반드시 백업할 것!

-- 1. 아티스트 external_id 변환: it_xxx → custom_xxx
UPDATE artists
SET artist_external_id = CONCAT('custom_', SUBSTRING(artist_external_id, 4))
WHERE artist_external_id LIKE 'it\_%';

-- 2. 노래 external_id 변환: it_xxx → custom_xxx
UPDATE songs
SET song_external_id = CONCAT('custom_', SUBSTRING(song_external_id, 4))
WHERE song_external_id LIKE 'it\_%';
