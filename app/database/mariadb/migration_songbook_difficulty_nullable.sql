-- ============================================
-- 노래책 수록곡 난이도를 선택사항으로 (NULL 허용)
-- ============================================
-- 적용 안내:
--   python migrate.py --file songbook_difficulty_nullable
--   기존 값은 그대로 유지되며, 앞으로 난이도 없이도 곡을 등록할 수 있습니다.
-- ============================================

ALTER TABLE `streamer_songbooks`
    MODIFY COLUMN `difficulty` TINYINT NULL COMMENT '난이도 (1~10), NULL=미설정';
