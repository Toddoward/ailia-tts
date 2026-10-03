import asyncio, json, base64, io
import websockets

async def test():
    chunks = []
    async with websockets.connect("ws://127.0.0.1:18766") as ws:
        await ws.send(json.dumps({"type": "turn_start", "turnId": "t1"}))
        await ws.send(json.dumps({"type": "text_delta", "turnId": "t1", "text": "안녕하세요. 저는 에일리아에요. 반가워요, 주인님."}))
        await ws.send(json.dumps({"type": "turn_end", "turnId": "t1"}))
        async for msg in ws:
            data = json.loads(msg)
            if data["type"] == "audio_chunk":
                chunks.append(base64.b64decode(data["data"]))
                print(f"chunk {data['seq']} 수신")
            elif data["type"] == "turn_done":
                break
            elif data["type"] == "error":
                print("에러:", data["message"])
                break
    
    # 각 청크를 파일로 저장 (WAV 헤더 포함되어 있음)
    for i, c in enumerate(chunks):
        with open(f"test_chunk_{i}.wav", "wb") as f:
            f.write(c)
    print(f"{len(chunks)}개 파일 저장됨. 직접 재생해 보세요.")

asyncio.run(test())
