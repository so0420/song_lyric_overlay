import asyncio
from app.database.mariadb import db_handler
from app.database.meilisearch.meilisearch import meilisearch_handler
from app.utils.log import logger

async def sync_owner_names():
    print("Fetching songs with owners from DB...")
    query = """
        SELECT s.id, s.title, s.song_external_id, u.name as owner_name, a.name as artist_name, s.cover_image_url
        FROM songs s
        LEFT JOIN users u ON s.owner_id = u.id
        LEFT JOIN artists a ON s.artist_id = a.id
        WHERE s.owner_id IS NOT NULL
    """
    songs = await db_handler.fetch_all(query)
    
    if not songs:
        print("No custom songs with owners found.")
        return

    documents = []
    for s in songs:
        documents.append({
            "id": s['id'],
            "title": s['title'],
            "singer": s['artist_name'],
            "image_url": s['cover_image_url'],
            "song_external_id": s['song_external_id'],
            "owner_name": s['owner_name']
        })
    
    print(f"Syncing {len(documents)} documents to Meilisearch...")
    res = await meilisearch_handler.update_documents(documents)
    print(f"Meilisearch update task: {res}")
    print("Sync complete.")

if __name__ == "__main__":
    asyncio.run(sync_owner_names())
