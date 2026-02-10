from fastapi import APIRouter, Depends, HTTPException
from typing import List, Dict, Any
from app.database.follow_repository import get_follow_repository
from app.core.auth import get_current_user_api

router = APIRouter()


@router.get("/")
async def get_my_followed_streamers(
    user=Depends(get_current_user_api),
    repo=Depends(get_follow_repository)
) -> List[Dict[str, Any]]:
    """내가 즐겨찾기한 스트리머 목록을 가져옵니다."""
    if not user:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    
    streamers = await repo.get_followed_streamers(user['id'])
    return [
        {
            "id": s['streamer_id'],
            "slug": s['slug'],
            "name": s['name'],
            "picture": s.get('picture'),
            "followed_at": s['followed_at'].isoformat() if s.get('followed_at') else None
        }
        for s in streamers
    ]


@router.post("/{streamer_id}")
async def follow_streamer(
    streamer_id: str,
    user=Depends(get_current_user_api),
    repo=Depends(get_follow_repository)
):
    """스트리머를 즐겨찾기에 추가합니다."""
    if not user:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    
    # 외부 streamer_id로 내부 id 조회
    internal_id = await repo.get_streamer_internal_id(streamer_id)
    if not internal_id:
        raise HTTPException(status_code=404, detail="스트리머를 찾을 수 없습니다.")
    
    await repo.follow_streamer(user['id'], internal_id)
    return {"success": True, "message": "즐겨찾기에 추가되었습니다."}


@router.delete("/{streamer_id}")
async def unfollow_streamer(
    streamer_id: str,
    user=Depends(get_current_user_api),
    repo=Depends(get_follow_repository)
):
    """스트리머를 즐겨찾기에서 삭제합니다."""
    if not user:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    
    internal_id = await repo.get_streamer_internal_id(streamer_id)
    if not internal_id:
        raise HTTPException(status_code=404, detail="스트리머를 찾을 수 없습니다.")
    
    await repo.unfollow_streamer(user['id'], internal_id)
    return {"success": True, "message": "즐겨찾기가 삭제되었습니다."}


@router.get("/{streamer_id}/status")
async def get_follow_status(
    streamer_id: str,
    user=Depends(get_current_user_api),
    repo=Depends(get_follow_repository)
):
    """특정 스트리머를 즐겨찾기 했는지 확인합니다."""
    if not user:
        return {"is_following": False}
    
    internal_id = await repo.get_streamer_internal_id(streamer_id)
    if not internal_id:
        raise HTTPException(status_code=404, detail="스트리머를 찾을 수 없습니다.")
    
    is_following = await repo.is_following(user['id'], internal_id)
    return {"is_following": is_following}
