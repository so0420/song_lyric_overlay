"""자동 가사(LRCLIB) 관련 순수 함수 테스트.

기존 테스트 스위트의 async_client/mock_db 픽스처 없이도 돌아가는
자립형(pure-function) 테스트만 둔다. 여기서 검증하는 _bake_offset 은
관리자 정식 등록 시 '이 곡만 오프셋' 을 타임스탬프에 반영하는 핵심 로직이다.
"""
import json

from app.api.v1.admin_auto_lyrics import _bake_offset


def _segs():
    return json.dumps([
        {"start": 1000, "end": 2000, "text": "a"},
        {"start": 2000, "end": 3000, "text": "b"},
    ])


class TestBakeOffset:
    def test_no_offset_returns_unchanged(self):
        data = _segs()
        assert _bake_offset(data, 0) == data

    def test_positive_offset_shifts_earlier(self):
        # 재생 규칙이 (currentTime + offset >= start) 이므로,
        # 양수 오프셋 → 타임스탬프를 그만큼 앞당겨(빼서) baking.
        out = json.loads(_bake_offset(_segs(), 500))
        assert out[0]["start"] == 500 and out[0]["end"] == 1500
        assert out[1]["start"] == 1500 and out[1]["end"] == 2500

    def test_negative_offset_shifts_later(self):
        out = json.loads(_bake_offset(_segs(), -300))
        assert out[0]["start"] == 1300 and out[0]["end"] == 2300
        assert out[1]["start"] == 2300 and out[1]["end"] == 3300

    def test_clamps_to_zero(self):
        out = json.loads(_bake_offset(_segs(), 5000))
        assert out[0]["start"] == 0 and out[0]["end"] == 0
        assert out[1]["start"] == 0 and out[1]["end"] == 0

    def test_invalid_json_returned_as_is(self):
        assert _bake_offset("not-json", 100) == "not-json"

    def test_empty_returns_input(self):
        assert _bake_offset("", 100) == ""
