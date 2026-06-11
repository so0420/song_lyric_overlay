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


def build_push_data(row: Dict[str, Any], auto_playlist: Optional[bool] = None) -> Dict[str, Any]:
    """song_request_new WS 푸시 / playlist-pending 응답용 데이터 구성

    - title/artist: 노래책 참조 곡 정보 우선, 없으면 신청 입력값(노래책 외 신청)
    - lyrics_id/lyrics_title: 유효(미삭제) 가사만 (JOIN 조건으로 이미 걸러짐)
    - mr_video_id: 수록곡 MR 우선, 없으면 가사의 MR
    """
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
        "mr_video_id": resolve_mr_video_id(row),
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
