#!/usr/bin/env python3
"""Ailia TTS WebSocket Test Client.

Reusable test client for the Ailia TTS v3 server.

Usage:
    python websocket_test.py                          # Basic test, save WAV files
    python websocket_test.py --play                    # Play audio in real-time
    python websocket_test.py --text "Hello world"     # Custom text
    python websocket_test.py --repeat 3                # Repeat test 3 times
    python websocket_test.py --rtf                     # Report RTF metrics

Protocol:
    Client -> Server: turn_start, text_delta, turn_end, cancel
    Server -> Client: audio_chunk, turn_done, error
"""
import asyncio
import argparse
import base64
import io
import json
import sys
import time
from pathlib import Path

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18766
DEFAULT_TEXT = "안녕하세요. 저는 에일리아에요. 반가워요, 주인님."


class TTSTestClient:
    """Reusable WebSocket test client for Ailia TTS server."""

    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT):
        self.uri = f"ws://{host}:{port}"
        self.chunks = []  # List of (seq, audio_bytes, recv_time)

    async def synthesize(self, text, turn_id="t1", verbose=True):
        """Send text and collect audio chunks. Returns list of audio bytes."""
        import websockets

        self.chunks = []
        start_wall = time.time()

        async with websockets.connect(self.uri) as ws:
            await ws.send(json.dumps({"type": "turn_start", "turnId": turn_id}))
            await ws.send(json.dumps({
                "type": "text_delta", "turnId": turn_id, "text": text
            }))
            await ws.send(json.dumps({"type": "turn_end", "turnId": turn_id}))

            async for msg in ws:
                data = json.loads(msg)
                mtype = data.get("type")

                if mtype == "audio_chunk":
                    audio = base64.b64decode(data["data"])
                    recv_time = time.time()
                    self.chunks.append((data["seq"], audio, recv_time))
                    if verbose:
                        print(f"  chunk {data['seq']} 수신 ({len(audio)} bytes)")

                elif mtype == "turn_done":
                    if verbose:
                        print(f"  turn_done ({len(self.chunks)} chunks)")
                    break

                elif mtype == "error":
                    print(f"  에러: {data.get('message')}", file=sys.stderr)
                    break

        total_wall = time.time() - start_wall
        return [c[1] for c in self.chunks], total_wall

    def save_wav_files(self, prefix="test_chunk"):
        """Save each chunk as a separate WAV file."""
        for i, (seq, audio, _) in enumerate(self.chunks):
            path = f"{prefix}_{i}.wav"
            with open(path, "wb") as f:
                f.write(audio)
        print(f"{len(self.chunks)}개 파일 저장됨: {prefix}_0.wav ~ {prefix}_{len(self.chunks)-1}.wav")

    def play_audio(self):
        """Play received audio chunks in real-time using sounddevice."""
        try:
            import sounddevice as sd
            import soundfile as sf
        except ImportError:
            print("재생을 위해 sounddevice와 soundfile이 필요합니다:", file=sys.stderr)
            print("  pip install sounddevice soundfile", file=sys.stderr)
            return False

        print("재생 중...")
        for seq, audio_bytes, _ in sorted(self.chunks):
            buf = io.BytesIO(audio_bytes)
            data, sr = sf.read(buf, dtype='int16')
            sd.play(data, sr)
            sd.wait()
        print("재생 완료")
        return True

    def report_rtf(self, total_wall_time):
        """Calculate and report Real-Time Factor metrics."""
        import soundfile as sf

        total_audio_sec = 0.0
        for seq, audio_bytes, _ in self.chunks:
            buf = io.BytesIO(audio_bytes)
            data, sr = sf.read(buf)
            total_audio_sec += len(data) / sr

        if total_audio_sec > 0:
            rtf = total_wall_time / total_audio_sec
            print(f"\n--- RTF 리포트 ---")
            print(f"  오디오 길이: {total_audio_sec:.2f}초")
            print(f"  소요 시간: {total_wall_time:.2f}초")
            print(f"  RTF: {rtf:.2f}x ({'실시간보다 ' + ('빠름' if rtf < 1 else f'{rtf:.1f}배 느림')})")
            print(f"  청크 수: {len(self.chunks)}")
        else:
            print("오디오 데이터 없음", file=sys.stderr)


async def run_test(args):
    """Run a single test with the given arguments."""
    client = TTSTestClient(host=args.host, port=args.port)

    print(f"서버 연결: {client.uri}")
    print(f"텍스트: {args.text}")

    chunks, wall_time = await client.synthesize(
        args.text, turn_id=args.turn_id, verbose=not args.quiet
    )

    if not chunks:
        print("오디오를 받지 못했습니다.", file=sys.stderr)
        return 1

    if args.play:
        client.play_audio()
    else:
        client.save_wav_files(prefix=args.output_prefix)

    if args.rtf:
        client.report_rtf(wall_time)

    return 0


def main():
    p = argparse.ArgumentParser(
        description="Ailia TTS v3 WebSocket 테스트 클라이언트",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예제:
  %(prog)s                                    # 기본 테스트
  %(prog)s --play                             # 실시간 재생
  %(prog)s --text "Hello, world!"              # 사용자 텍스트
  %(prog)s --repeat 3 --rtf                   # 3회 반복 + RTF 리포트
  %(prog)s --host 192.168.1.100               # 원격 서버
        """,
    )
    p.add_argument("--host", default=DEFAULT_HOST, help=f"서버 호스트 (기본: {DEFAULT_HOST})")
    p.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"서버 포트 (기본: {DEFAULT_PORT})")
    p.add_argument("--text", default=DEFAULT_TEXT, help="합성할 텍스트")
    p.add_argument("--turn-id", default="t1", help="턴 ID (기본: t1)")
    p.add_argument("--play", action="store_true", help="WAV 저장 대신 실시간 재생")
    p.add_argument("--output-prefix", default="test_chunk", help="출력 파일 접두사 (기본: test_chunk)")
    p.add_argument("--repeat", type=int, default=1, help="반복 횟수 (기본: 1)")
    p.add_argument("--rtf", action="store_true", help="RTF (Real-Time Factor) 리포트 출력")
    p.add_argument("--quiet", action="store_true", help="청크 수신 로그 숨김")

    args = p.parse_args()

    exit_code = 0
    for i in range(args.repeat):
        if args.repeat > 1:
            print(f"\n=== 반복 {i+1}/{args.repeat} ===")
            args.turn_id = f"t{i+1}"
        code = asyncio.run(run_test(args))
        if code != 0:
            exit_code = code
            break
        if i < args.repeat - 1:
            time.sleep(1)  # 반복 사이 간격

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
