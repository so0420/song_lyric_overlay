import asyncio
import aiohttp
import json
import sys

async def run_ws_client(token, events=None):
    """
    WebSocket 테스트 클라이언트를 실행합니다. (토큰 전용 주소 사용)
    """
    # 이제 URL에 streamer_id가 필요 없고 토큰이 경로에 들어갑니다.
    url = f"ws://localhost:8006/api/v1/ws/{token}"
    if events:
        url += f"&events={events}"
        
    print(f"Connecting to {url}...")
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.ws_connect(url) as ws:
                print("Successfully connected to WebSocket!")
                
                # 메시지 수신 핸들러를 별도 태스크로 실행
                async def receive_messages():
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)
                            print(f"\n[Received] {json.dumps(data, indent=2, ensure_ascii=False)}")
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            print(f"WebSocket closed with error: {ws.exception()}")
                            break
                        elif msg.type == aiohttp.WSMsgType.CLOSED:
                            print("WebSocket connection closed.")
                            break

                receive_task = asyncio.create_task(receive_messages())
                
                print("\nAvailable commands:")
                print("1. sub [EVENT1,EVENT2] - Update subscription events")
                print("2. quit - Exit client")
                
                while True:
                    loop = asyncio.get_event_loop()
                    cmd_line = await loop.run_in_executor(None, sys.stdin.readline)
                    cmd_line = cmd_line.strip()
                    
                    if not cmd_line:
                        continue
                        
                    if cmd_line == "quit":
                        break
                    elif cmd_line.startswith("sub "):
                        event_list = cmd_line[4:].split(",")
                        await ws.send_json({"action": "subscribe", "events": event_list})
                        print(f"Sent subscription update for: {event_list}")
                
                receive_task.cancel()
                await ws.close()
                
        except Exception as e:
            print(f"Connection failed: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python websocket_test.py <token> [events]")
        print("Example: python websocket_test.py my_secret_token NEW_SONG,LYRICS")
        sys.exit(1)
        
    tk = sys.argv[1]
    ev = sys.argv[2] if len(sys.argv) > 2 else None
    
    asyncio.run(run_ws_client(tk, ev))
