-- ============================================
-- 자동 가사 기록에 'editing'(편집 중) 상태 추가
-- ============================================
-- 적용 안내:
--   python migrate.py --file auto_lyrics_editing_status
--
-- 배경:
--   관리자가 '편집기에서 보기'를 누르면 해당 기록이 검토(pending) 리스트에서 빠지고
--   가사 편집기로 이동한다(자동가사+오프셋 반영 상태). 편집기에서 저장하면 정식
--   등록(registered)된다. 열었지만 아직 저장 안 한 상태를 'editing' 으로 구분해,
--   pending 목록에서 사라지되(중복 처리 방지) 잃어버리지 않고 '편집 중' 필터로 다시
--   열 수 있게 한다.
-- ============================================

ALTER TABLE `auto_lyrics_imports`
    MODIFY COLUMN `status` ENUM('pending','editing','registered','ignored')
    NOT NULL DEFAULT 'pending' COMMENT '검토 상태';
