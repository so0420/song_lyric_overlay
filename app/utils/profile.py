import httpx
import uuid
import mimetypes
from app.database.cloudflare.r2 import R2Handler
from app.utils.config import settings
from app.utils.log import logger

async def save_profile_image_from_url(url: str, r2_handler: R2Handler) -> str:
    """
    외부 URL에서 이미지를 다운로드하여 R2에 저장하고 공개 URL을 반환합니다.
    """
    if not url:
        return None
        
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
            content = response.content
            
            # 컨텐츠 타입 확인 (이미지인지 확인)
            content_type = response.headers.get("Content-Type", "")
            if not content_type.startswith("image/"):
                # 기본 확장자 처리
                content_type = "image/jpeg"
                
            # 확장자 추정
            ext = mimetypes.guess_extension(content_type) or ".jpg"
            
            # 파일명 생성
            filename = f"profiles/{uuid.uuid4()}{ext}"
            
            # R2 업로드
            await r2_handler.upload_file(content, filename, content_type)
            
            # 공개 URL 반환
            base_url = settings.cloudflare_public_url.rstrip("/")
            if not base_url.startswith(("http://", "https://")):
                base_url = f"https://{base_url}"
                
            return f"{base_url}/{filename}"
            
        except Exception as e:
            logger.error(f"Failed to save profile image: {e}")
            return url  # 실패 시 원본 URL 반환 (fallback)
