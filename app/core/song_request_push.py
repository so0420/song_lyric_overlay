"""노래 신청 → 노래하기(singer) 페이지 WS 푸시 공통 로직

웹 신청(app/api/v1/song_requests.py)과 치지직 채팅/후원 신청
(app/integrations/chzzk_connection/chzzk_event_handler.py)이 동일한 계약으로
song_request_new 메시지를 보내도록 공유한다.
"""
from typing import Any, Dict, Optional

from app.core.overlay_websocket import overlay_manager
from app.utils.log import logger


def resolve_mr_video_id(row: Dict[str, Any]) -> Optional[str]:
    """MR 영상 ID 해석: 노래책 수록곡 MR 우선, 없으면 연결 가사의 MR"""
    return row.get("sb_mr_video_id") or row.get("lyrics_mr_video_id")


def resolve_mr_source(row: Dict[str, Any]) -> Dict[str, Any]:
    """재생 소스 해석 결과 {"type": "audio"|"youtube"|None, "video_id":…, "audio_file_id":…}

    우선순위: ① 수록곡 지정 음원 → ② 수록곡 지정 유튜브 MR
              → ③ 가사의 음원   → ④ 가사의 유튜브 MR

    '수록곡(스트리머 개인 설정)이 가사(공용)를 항상 이긴다'는 기존 MR 규칙을 그대로 따른다.
    소스 종류별로 먼저 훑으면(음원 전부 → 유튜브 전부) 스트리머가 명시적으로 지정한
    수록곡 유튜브 MR 이 가사의 음원에 밀려 무시되므로, 계층을 바깥 루프로 둔다.
    """
    for audio_key, video_key in (
        ("sb_audio_file_id", "sb_mr_video_id"),
        ("lyrics_audio_file_id", "lyrics_mr_video_id"),
    ):
        if row.get(audio_key):
            return {"type": "audio", "video_id": None, "audio_file_id": row[audio_key]}
        if row.get(video_key):
            return {"type": "youtube", "video_id": row[video_key], "audio_file_id": None}
    return {"type": None, "video_id": None, "audio_file_id": None}


def build_push_data(row: Dict[str, Any], auto_playlist: Optional[bool] = None) -> Dict[str, Any]:
    """song_request_new WS 푸시 / playlist-pending 응답용 데이터 구성

    - title/artist: 노래책 참조 곡 정보 우선, 없으면 신청 입력값(노래책 외 신청)
    - lyrics_id/lyrics_title: 유효(미삭제) 가사만 (JOIN 조건으로 이미 걸러짐)
    - mr_video_id / audio_file_id: 수록곡 지정 소스 우선, 없으면 가사의 소스 (resolve_mr_source)
    """
    source = resolve_mr_source(row)
    data = {
        "request_id": row["id"],
        "requester": row["requester"],
        "requester_type": row["requester_type"],
        "title": row.get("ref_song_title") or row.get("title"),
        "artist": row.get("ref_artist_name") or row.get("artist"),
        "song_id": row.get("song_id"),
        "song_external_id": row.get("song_external_id"),
        "lyrics_id": row.get("ref_lyrics_id"),
        "lyrics_title": row.get("ref_lyrics_title"),
        "mr_video_id": source["video_id"],
        "source_type": source["type"],
        "audio_file_id": source["audio_file_id"],
        "cover_image_url": row.get("ref_song_cover"),
        "is_in_songbook": row.get("is_in_songbook", 0),
    }
    if auto_playlist is not None:
        data["auto_playlist"] = auto_playlist
    return data


async def broadcast_new_request(streamer_user_id: int, row: Dict[str, Any], auto_playlist: bool) -> None:
    """노래하기 페이지(singer)로 신규 신청 푸시 (실패해도 호출부 흐름은 유지)"""
    try:
        await overlay_manager.broadcast_to_singers(
            streamer_user_id,
            {"type": "song_request_new", "data": build_push_data(row, auto_playlist=auto_playlist)},
        )
    except Exception as e:
        logger.warning(f"[song_request_push] WS 푸시 실패 (request_id={row.get('id')}): {e}")
