-- ============================================
-- 탈퇴 계정 개인정보 자동 파기 + 같은 이메일로 재가입 허용
-- ============================================
-- 적용 안내:
--   python migrate.py --file account_purge
--
-- 배경:
--   탈퇴는 소프트 삭제(deleted_at)만 하고 있어 이메일·이름·비밀번호 해시 등이
--   계속 남아 있었다. 개인정보 처리방침에 맞춰 탈퇴 후 일정 기간이 지나면
--   식별정보만 자동으로 지우되, users 행 자체는 남겨 가사·노래책 등
--   연결된 데이터가 깨지지 않게 한다.
--
--   또 email 이 NOT NULL UNIQUE 라서 탈퇴한 이메일로는 재가입이 막혀 있었다.
--   파기 시 email 을 NULL 로 만들 수 있어야 그 이메일이 다시 풀린다.
--   (MariaDB 의 UNIQUE 인덱스는 NULL 을 중복으로 보지 않는다)
-- ============================================

-- 파기 시 NULL 로 비울 수 있도록 이메일을 NULL 허용으로 변경
ALTER TABLE `users`
    MODIFY COLUMN `email` VARCHAR(255) NULL COMMENT '사용자 이메일 (탈퇴 후 파기 시 NULL)';

-- 파기 완료 시각. 이미 파기한 행을 다시 훑지 않기 위한 표시이기도 하다.
ALTER TABLE `users`
    ADD COLUMN `purged_at` TIMESTAMP NULL COMMENT '탈퇴 후 개인정보 파기 완료 일시' AFTER `deleted_at`;

-- 파기 대상(탈퇴했고 아직 파기 전)을 훑는 쿼리용 인덱스
ALTER TABLE `users`
    ADD INDEX `idx_users_purge_target` (`purged_at`, `deleted_at`);
