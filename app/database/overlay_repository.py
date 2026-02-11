from app.database.mariadb import db_handler
from app.schemas.overlay import OverlaySettingsSchema
from typing import Optional, Dict, Any
import json


class OverlayRepository:
    def __init__(self, db=db_handler):
        self.db = db

    async def get_settings(self, user_id: int) -> Optional[Dict[str, Any]]:
        """사용자의 오버레이 설정 조회"""
        result = await self.db.fetch_one(
            "SELECT settings_json FROM user_overlay_settings WHERE user_id = %s",
            (user_id,)
        )
        if result and result['settings_json']:
            return json.loads(result['settings_json'])
        return None

    async def save_settings(self, user_id: int, settings: OverlaySettingsSchema) -> bool:
        """사용자의 오버레이 설정 저장 (UPSERT)"""
        settings_json = json.dumps(settings.model_dump())

        existing = await self.db.fetch_one(
            "SELECT id FROM user_overlay_settings WHERE user_id = %s",
            (user_id,)
        )

        if existing:
            await self.db.execute_query(
                "UPDATE user_overlay_settings SET settings_json = %s, updated_at = CURRENT_TIMESTAMP WHERE user_id = %s",
                (settings_json, user_id)
            )
        else:
            await self.db.execute_query(
                "INSERT INTO user_overlay_settings (user_id, settings_json) VALUES (%s, %s)",
                (user_id, settings_json)
            )
        return True


def get_overlay_repository() -> OverlayRepository:
    return OverlayRepository()
