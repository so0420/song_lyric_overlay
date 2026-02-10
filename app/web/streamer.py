from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from app.utils.templates import templates
from app.database.streamer_repository import get_streamer_repository
from app.core.auth import get_current_user
from app.utils.config import config

router = APIRouter()

@router.get("/manage", response_class=HTMLResponse)
async def manage_songbook(
    request: Request,
    user=Depends(get_current_user),
    repo=Depends(get_streamer_repository)
):
    if not user:
        return HTMLResponse(content="<script>alert('로그인이 필요합니다.'); window.location.href='/login';</script>")
    
    return templates.TemplateResponse("pages/streamer/dashboard.html", {
        "request": request,
        "user": user,
        "config": config
    })

@router.get("/@{slug}", response_class=HTMLResponse)
async def streamer_page_by_slug(
    request: Request,
    slug: str,
    user=Depends(get_current_user),
    repo=Depends(get_streamer_repository)
):
    streamer = await repo.get_streamer_by_slug(slug)
    return await render_streamer_view(request, streamer, user)

@router.get("/{streamer_id}", response_class=HTMLResponse)
async def streamer_page_by_id(
    request: Request,
    streamer_id: str,
    user=Depends(get_current_user),
    repo=Depends(get_streamer_repository)
):
    streamer = await repo.get_streamer_by_streamer_id(streamer_id)
    return await render_streamer_view(request, streamer, user)

async def render_streamer_view(request, streamer, user):
    if not streamer:
        raise HTTPException(status_code=404, detail="Streamer not found")
    
    # JSON Parsing for template
    import json
    if streamer.get('tags'):
        try:
            streamer['tags'] = json.loads(streamer['tags'])
        except:
            streamer['tags'] = []
    else:
        streamer['tags'] = []
        
    return templates.TemplateResponse("pages/streamer/streamer_view.html", {
        "request": request,
        "user": user,
        "config": config,
        "streamer": {
            "id": streamer['streamer_id'],
            "slug": streamer['slug'],
            "name": streamer['name'],
            "description": streamer['description'],
            "tags": streamer['tags'],
            "picture": streamer.get('picture')
        }
    })
