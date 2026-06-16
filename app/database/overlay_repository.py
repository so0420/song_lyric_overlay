from app.database.mariadb import db_handler
from app.schemas.overlay import OverlaySettingsSchema, OverlayPresetCreateSchema, OverlayPresetUpdateSchema
from typing import Optional, Dict, Any, List
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

    # ============ Preset Methods ============

    async def get_presets(self, user_id: int) -> List[Dict[str, Any]]:
        """사용자의 모든 프리셋 조회"""
        results = await self.db.fetch_all(
            """SELECT id, name, settings_json, is_active, created_at, updated_at
               FROM user_overlay_presets
               WHERE user_id = %s
               ORDER BY created_at DESC""",
            (user_id,)
        )
        presets = []
        for row in results:
            presets.append({
                'id': row['id'],
                'name': row['name'],
                'settings': json.loads(row['settings_json']) if row['settings_json'] else {},
                'is_active': bool(row['is_active']),
                'created_at': row['created_at'],
                'updated_at': row['updated_at']
            })
        return presets

    async def get_preset(self, preset_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        """특정 프리셋 조회"""
        result = await self.db.fetch_one(
            """SELECT id, name, settings_json, is_active, created_at, updated_at
               FROM user_overlay_presets
               WHERE id = %s AND user_id = %s""",
            (preset_id, user_id)
        )
        if result:
            return {
                'id': result['id'],
                'name': result['name'],
                'settings': json.loads(result['settings_json']) if result['settings_json'] else {},
                'is_active': bool(result['is_active']),
                'created_at': result['created_at'],
                'updated_at': result['updated_at']
            }
        return None

    async def create_preset(self, user_id: int, data: OverlayPresetCreateSchema) -> int:
        """프리셋 생성"""
        settings_json = json.dumps(data.settings.model_dump())
        preset_id = await self.db.execute_query(
            """INSERT INTO user_overlay_presets (user_id, name, settings_json, is_active)
               VALUES (%s, %s, %s, 0)""",
            (user_id, data.name, settings_json)
        )
        return preset_id

    async def update_preset(self, preset_id: int, user_id: int, data: OverlayPresetUpdateSchema) -> bool:
        """프리셋 수정"""
        # 먼저 소유권 확인
        existing = await self.get_preset(preset_id, user_id)
        if not existing:
            return False

        updates = []
        params = []

        if data.name is not None:
            updates.append("name = %s")
            params.append(data.name)

        if data.settings is not None:
            updates.append("settings_json = %s")
            params.append(json.dumps(data.settings.model_dump()))

        if not updates:
            return True  # 변경할 내용이 없으면 성공으로 처리

        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.extend([preset_id, user_id])

        await self.db.execute_query(
            f"UPDATE user_overlay_presets SET {', '.join(updates)} WHERE id = %s AND user_id = %s",
            tuple(params)
        )
        return True

    async def delete_preset(self, preset_id: int, user_id: int) -> bool:
        """프리셋 삭제"""
        result = await self.db.execute_query(
            "DELETE FROM user_overlay_presets WHERE id = %s AND user_id = %s",
            (preset_id, user_id)
        )
        return result > 0

    async def activate_preset(self, preset_id: int, user_id: int) -> bool:
        """프리셋 활성화 (다른 프리셋은 비활성화)"""
        # 먼저 소유권 확인
        existing = await self.get_preset(preset_id, user_id)
        if not existing:
            return False

        # 모든 프리셋 비활성화
        await self.db.execute_query(
            "UPDATE user_overlay_presets SET is_active = 0 WHERE user_id = %s",
            (user_id,)
        )

        # 선택된 프리셋 활성화
        await self.db.execute_query(
            "UPDATE user_overlay_presets SET is_active = 1 WHERE id = %s AND user_id = %s",
            (preset_id, user_id)
        )

        # 활성화된 프리셋의 설정을 현재 설정으로 복사
        preset = await self.get_preset(preset_id, user_id)
        if preset:
            settings = OverlaySettingsSchema(**preset['settings'])
            await self.save_settings(user_id, settings)

        return True

    # ============ Playlist Methods ============

    async def get_playlist(self, user_id: int) -> Dict[str, Any]:
        """사용자의 재생목록 조회. 없으면 빈 목록 반환."""
        result = await self.db.fetch_one(
            "SELECT playlist_json, current_index FROM user_playlists WHERE user_id = %s",
            (user_id,)
        )
        if not result:
            return {"playlist": [], "current_index": -1}
        try:
            playlist = json.loads(result['playlist_json']) if result['playlist_json'] else []
        except (ValueError, TypeError):
            playlist = []
        if not isinstance(playlist, list):
            playlist = []
        return {
            "playlist": playlist,
            "current_index": result['current_index'] if result['current_index'] is not None else -1,
        }

    async def save_playlist(self, user_id: int, playlist: List[Dict[str, Any]], current_index: int = -1) -> bool:
        """사용자의 재생목록 저장 (UPSERT)"""
        playlist_json = json.dumps(playlist, ensure_ascii=False)
        await self.db.execute_query(
            """INSERT INTO user_playlists (user_id, playlist_json, current_index)
               VALUES (%s, %s, %s)
               ON DUPLICATE KEY UPDATE
                   playlist_json = VALUES(playlist_json),
                   current_index = VALUES(current_index),
                   updated_at = CURRENT_TIMESTAMP""",
            (user_id, playlist_json, current_index)
        )
        return True

    async def get_active_preset(self, user_id: int) -> Optional[Dict[str, Any]]:
        """현재 활성화된 프리셋 조회"""
        result = await self.db.fetch_one(
            """SELECT id, name, settings_json, is_active, created_at, updated_at
               FROM user_overlay_presets
               WHERE user_id = %s AND is_active = 1""",
            (user_id,)
        )
        if result:
            return {
                'id': result['id'],
                'name': result['name'],
                'settings': json.loads(result['settings_json']) if result['settings_json'] else {},
                'is_active': True,
                'created_at': result['created_at'],
                'updated_at': result['updated_at']
            }
        return None


def get_overlay_repository() -> OverlayRepository:
    return OverlayRepository()
