from fastapi import APIRouter, Request, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from app.database.streamer_repository import get_streamer_repository
from app.core.auth import get_current_user, get_current_user_api
import json

router = APIRouter()

class StreamerProfileSchema(BaseModel):
    slug: Optional[str] = None
    description: Optional[str] = None
    links: List[Dict[str, str]] = []
    tags: List[Dict[str, str]] = []
    request_enabled: Optional[bool] = None
    request_chat_enabled: Optional[bool] = None
    request_donation_enabled: Optional[bool] = None
    request_web_enabled: Optional[bool] = None
    default_price_cheese: Optional[int] = None
    default_price_balloon: Optional[int] = None

@router.get("/")
async def get_streamers(q: str = Query(None), repo=Depends(get_streamer_repository)):
    query = """
        SELECT s.*, u.name, u.picture 
        FROM streamers s
        JOIN users u ON s.user_id = u.id
    """
    params = []
    if q:
        query += " WHERE u.name LIKE %s OR s.slug LIKE %s"
        params.extend([f"%{q}%", f"%{q}%"])
    
    results = await repo.db.fetch_all(query, tuple(params))
    for s in results:
        try:
            s['tags'] = json.loads(s['tags'])
        except:
            s['tags'] = []
            
    return [
        {
            "id": s['streamer_id'], 
            "name": s['name'], 
            "slug": s['slug'],
            "description": s['description'], 
            "tags": s['tags'],
            "picture": s.get('picture')
        } 
        for s in results
    ]

@router.get("/me")
async def get_my_streamer_profile(user=Depends(get_current_user_api), repo=Depends(get_streamer_repository)):
    if not user:
        return {"has_profile": False}
    
    profile = await repo.get_streamer_by_user_id(user['id'])
    if profile:
        # JSON fields processing
        try:
            profile['links'] = json.loads(profile['social_links'])
        except:
            profile['links'] = []
        try:
            profile['tags'] = json.loads(profile['tags'])
        except:
            profile['tags'] = []
        
        return {
            "has_profile": True,
            "profile": {
                "id": profile['streamer_id'],
                "name": profile['name'],
                "slug": profile['slug'],
                "description": profile['description'],
                "links": profile['links'],
                "tags": profile['tags'],
                "picture": profile.get('picture'),
                "request_enabled": bool(profile['request_enabled']),
                "request_chat_enabled": bool(profile['request_chat_enabled']),
                "request_donation_enabled": bool(profile['request_donation_enabled']),
                "request_web_enabled": bool(profile['request_web_enabled']),
                "default_price_cheese": profile['default_price_cheese'],
                "default_price_balloon": profile['default_price_balloon'],
            }
        }
    return {"has_profile": False}

@router.post("/")
async def create_my_profile(user=Depends(get_current_user_api), repo=Depends(get_streamer_repository)):
    # Generate unique slug
    base_slug = user['name'] or f"user_{user['id']}"
    slug = base_slug
    counter = 1
    
    while await repo.is_slug_taken(slug):
        slug = f"{base_slug}{counter}"
        counter += 1
        
    await repo.create_streamer_profile(user['id'], slug)
    return {"success": True}

@router.patch("/me")
async def update_my_profile(data: StreamerProfileSchema, user=Depends(get_current_user_api), repo=Depends(get_streamer_repository)):
    
    profile = await repo.get_streamer_by_user_id(user['id'])
    if not profile:
        raise HTTPException(status_code=404)

    # Check if slug is updated and unique
    slug = data.slug or profile['slug']
    if slug != profile['slug']:
        if await repo.is_slug_taken(slug, exclude_user_id=user['id']):
            raise HTTPException(status_code=400, detail="이미 사용 중인 주소입니다.")

    query = """
        UPDATE streamers 
        SET slug = %s, description = %s, social_links = %s, tags = %s,
            request_enabled = %s, request_chat_enabled = %s, request_donation_enabled = %s, request_web_enabled = %s,
            default_price_cheese = %s, default_price_balloon = %s
        WHERE id = %s
    """
    await repo.db.execute_query(query, (
        slug,
        data.description if data.description is not None else profile['description'], 
        json.dumps(data.links) if data.links is not None else profile['social_links'], 
        json.dumps(data.tags) if data.tags is not None else profile['tags'],
        int(data.request_enabled) if data.request_enabled is not None else profile['request_enabled'],
        int(data.request_chat_enabled) if data.request_chat_enabled is not None else profile['request_chat_enabled'],
        int(data.request_donation_enabled) if data.request_donation_enabled is not None else profile['request_donation_enabled'],
        int(data.request_web_enabled) if data.request_web_enabled is not None else profile['request_web_enabled'],
        data.default_price_cheese if data.default_price_cheese is not None else profile['default_price_cheese'],
        data.default_price_balloon if data.default_price_balloon is not None else profile['default_price_balloon'],
        profile['id']
    ))
    return {"success": True}

@router.delete("/me")
async def delete_my_streamer_profile(user=Depends(get_current_user_api), repo=Depends(get_streamer_repository)):
    profile = await repo.get_streamer_by_user_id(user['id'])
    if not profile:
        raise HTTPException(status_code=404, detail="Streamer profile not found")
        
    await repo.db.execute_query(
        "DELETE FROM streamers WHERE id = %s",
        (profile['id'],)
    )
    return {"success": True}
