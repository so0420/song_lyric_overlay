from app.utils.config import settings
from app.utils.log import logger
from meilisearch_python_sdk import AsyncClient
from meilisearch_python_sdk.models.settings import TypoTolerance
from typing import List, Optional, Dict, Any
import asyncio


class MeilisearchSearch:
    def __init__(self):
        self.client = AsyncClient(
            settings.meilisearch_host,
            settings.meilisearch_api_key
        )
        self.index_name = settings.meilisearch_index_name
        # Note: Index operations are now async, so we don't ensure index in __init__.
        # Becuase __init__ cannot be async.
        self.index = self.client.index(self.index_name)

    async def initialize(self):
        """Meilisearch 초기화: 인덱스 확인 및 생성"""
        if not await self.index_exists():
            await self.create_index()
            # 초기 설정 (필요 시)
            await self.update_searchable_attributes(["title", "singer"])
            await self.update_filterable_attributes(["singer"])

    async def close(self):
        """클라이언트 종료"""
        await self.client.aclose()

    # ---------------------------
    # Meilisearch 검색용 키 생성
    # ---------------------------
    async def create_search_key(self):
        try:
            # 0.40.0 대응: dict 형태로 전달 및 camelCase 사용
            key_options = {
                "description": "Search Key",
                "actions": ["search"],
                "indexes": [self.index_name],
                "expiresAt": None,
            }
            key = await self.client.create_key(key_options)
            return key
        except Exception as e:
            logger.error(f"Create search key error: {e}")
            return None

    # ---------------------------
    # Index 관련
    # ---------------------------
    async def get_index_lists_by_page(self, page: int = 1, size: int = 20):
        offset = (page - 1) * size
        try:
            return await self.client.get_indexes(offset=offset, limit=size)
        except Exception as e:
            logger.error(f"Get index lists error: {e}")
            return None
    
    async def get_all_index_lists(self, batch_size: int = 100):
        """
        모든 인덱스 목록을 전부 가져온다.
        meilisearch-python-sdk의 get_indexes는 AsyncIndex 객체들의 리스트를 반환합니다.
        """
        try:
            all_results = []
            offset = 0

            while True:
                resp = await self.client.get_indexes(offset=offset, limit=batch_size)
                if not resp:
                    break

                # resp는 list[AsyncIndex] 형태입니다.
                all_results.extend(resp)

                # 더 가져올 게 없으면 종료 (가져온 개수가 요청한 batch_size보다 작으면 마지막 페이지)
                if len(resp) < batch_size:
                    break

                offset += batch_size

            return all_results
        except Exception as e:
            logger.error(f"Get all index lists error: {e}")
            return None

    async def index_exists(self, index_name: str = None) -> bool:
        index_name = index_name or self.index_name
        try:
            indexes = await self.get_all_index_lists()
            if not indexes:
                return False
            return any(idx.uid == index_name for idx in indexes)
        except Exception as e:
            logger.error(f"Index exists error: {e}")
            return False

    async def create_index(self, primary_key: str = "id"):
        try:
            # meilisearch-python-sdk: create_index(uid, primary_key=None)
            res = await self.client.create_index(self.index_name, primary_key=primary_key)
            logger.info(f"Create index success: {res}")
            return res
        except Exception as e:
            logger.error(f"Create index error: {e}")
            return None

    async def delete_index(self):
        try:
            return await self.client.delete_index(self.index_name)
        except Exception as e:
            logger.error(f"Delete index error: {e}")
            return None

    async def get_index_stats(self) -> Dict[str, Any]:
        try:
            stats = await self.index.get_stats()
            return stats.model_dump() if hasattr(stats, 'model_dump') else vars(stats)
        except Exception as e:
            logger.error(f"Get index stats error: {e}")
            return {}

    # ---------------------------
    # Document 관련
    # ---------------------------
    async def add_documents(self, documents: List[dict]):
        try:
            return await self.index.add_documents(documents)
        except Exception as e:
            logger.error(f"Add documents error: {e}")
            return None

    async def update_documents(self, documents: List[dict]):
        try:
            return await self.index.update_documents(documents)
        except Exception as e:
            logger.error(f"Update documents error: {e}")
            return None

    async def get_document_by_id(self, document_id: Any) -> Optional[dict]:
        try:
            doc = await self.index.get_document(str(document_id))
            # Pydantic 모델이거나 객체일 수 있으므로 dict로 변환
            if hasattr(doc, 'model_dump'):
                return doc.model_dump()
            return vars(doc) if doc else None
        except Exception as e:
            logger.error(f"Get document error: {e}")
            return None

    async def delete_document_by_id(self, document_id: Any):
        try:
            return await self.index.delete_document(str(document_id))
        except Exception as e:
            logger.error(f"Delete document error: {e}")
            return None

    async def delete_documents_by_ids(self, document_ids: List[Any]):
        try:
            return await self.index.delete_documents(document_ids)
        except Exception as e:
            logger.error(f"Delete documents error: {e}")
            return None

    # ---------------------------
    # Search 관련
    # ---------------------------
    async def search(
            self,
            query: str,
            limit: int = 20,
            offset: int = 0,
            filter: Optional[str] = None,
            sort: Optional[List[str]] = None,
            attributes_to_search_on: Optional[List[str]] = None,
    ) -> List[dict]:
        try:
            # meilisearch-python-sdk search parameters are slightly different
            search_results = await self.index.search(
                query,
                limit=limit,
                offset=offset,
                filter=filter,
                sort=sort,
                attributes_to_search_on=attributes_to_search_on
            )
            return [hit if isinstance(hit, dict) else (hit.model_dump() if hasattr(hit, 'model_dump') else vars(hit)) for hit in search_results.hits]
        except Exception as e:
            logger.error(f"Search error: {e}")
            return []

    # ---------------------------
    # Settings 관련
    # ---------------------------
    async def update_searchable_attributes(self, attributes: List[str]):
        try:
            return await self.index.update_searchable_attributes(attributes)
        except Exception as e:
            logger.error(f"Update searchable attributes error: {e}")
            return None

    async def update_filterable_attributes(self, attributes: List[str]):
        try:
            return await self.index.update_filterable_attributes(attributes)
        except Exception as e:
            logger.error(f"Update filterable attributes error: {e}")
            return None

    async def update_sortable_attributes(self, attributes: List[str]):
        try:
            return await self.index.update_sortable_attributes(attributes)
        except Exception as e:
            logger.error(f"Update sortable attributes error: {e}")
            return None

    async def update_typo_tolerance(self, typo_settings: Dict[str, Any]):
        """
        오타 보정(Typo Tolerance) 설정 업데이트
        예시:
        {
            "enabled": True,
            "minWordSizeForTypos": {
                "oneTypo": 4,  # 4글자부터 오타 1개 허용
                "twoTypos": 8  # 8글자부터 오타 2개 허용
            },
            "disableOnAttributes": ["singer"] # 가수 이름은 오타 보정 제외
        }
        """
        try:
            return await self.index.update_typo_tolerance(TypoTolerance(**typo_settings))
        except Exception as e:
            logger.error(f"Update typo tolerance error: {e}")
            return None

    # ---------------------------
    # Task 관련
    # ---------------------------
    async def wait_for_task(self, task_uid: int, timeout_in_ms: int = 5000):
        try:
            return await self.client.wait_for_task(task_uid, timeout_in_ms=timeout_in_ms)
        except Exception as e:
            logger.error(f"Wait for task error: {e}")
            return None


if __name__ == "__main__":
    async def main():
        meilisearch = MeilisearchSearch()
        # 인덱스가 없을 경우 생성하는 로직이 MeilisearchSearch.__init__에서 빠졌으므로 필요시 호출
        if not await meilisearch.index_exists():
            await meilisearch.create_index()
        
        #await meilisearch.add_documents([
        #    {
        #        "id": 1,
        #        "title": "어푸",
        #        "singer": "아이유",
        #        "image_url": "https://example.com/image.jpg",
        #        "length": 300,
        #        "youtube": "https://www.youtube.com/watch?v=skmjmyluyNg"
        #    }
        #])

        results = await meilisearch.search("어푸", attributes_to_search_on=["title", "singer"])
        print(results)
    asyncio.run(main())

meilisearch_handler = MeilisearchSearch()
