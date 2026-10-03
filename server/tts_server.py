#!/usr/bin/env python3
"""Ailia TTS v3 - Thin WebSocket wrapper around official CosyVoice3.

Protocol:
  Client -> Server:
    {"type": "turn_start", "turnId": str}
    {"type": "text_delta", "turnId": str, "text": str}
    {"type": "turn_end", "turnId": str}
    {"type": "cancel", "turnId": str}

  Server -> Client:
    {"type": "audio_chunk", "turnId": str, "seq": int, "data": str (b64 wav)}
    {"type": "turn_done", "turnId": str}
    {"type": "error", "turnId": str, "message": str}

True bi-streaming: text deltas are fed to the model immediately,
audio chunks stream back as generated. No sentence buffering.
"""

import argparse
import asyncio
import base64
import io
import json
import logging
from pathlib import Path

import numpy as np

logging.basicConfig(level=logging.INFO, format='[tts] %(message)s')
log = logging.getLogger(__name__)

SAMPLE_RATE = 24000


class TTSStreamer:
    """Thin wrapper around official CosyVoice3 streaming API."""

    def __init__(self, model_dir: str, prompt_wav: str, prompt_text: str, fp16: bool = True):
        from cosyvoice.cli.cosyvoice import AutoModel
        log.info(f"Loading CosyVoice3 from {model_dir}...")
        self.model = AutoModel(model_dir=model_dir, fp16=fp16)
        self.prompt_wav = prompt_wav
        self.prompt_text = prompt_text
        self.sample_rate = self.model.sample_rate
        log.info("CosyVoice3 ready!")

    def synthesize_stream(self, text: str):
        """Yield (seq, audio_chunk_int16) as the model generates.

        Uses official streaming inference. Each yielded chunk is
        ready to send immediately — no waiting for full synthesis.
        """
        seq = 0
        for _, result in enumerate(
            self.model.inference_zero_shot(
                text, self.prompt_text, self.prompt_wav, stream=True
            )
        ):
            audio = result["tts_speech"]
            if hasattr(audio, "cpu"):
                audio = audio.cpu().numpy()
            audio = np.asarray(audio).squeeze()
            # Normalize to int16
            if audio.dtype != np.int16:
                audio = np.clip(audio, -1.0, 1.0)
                audio = (audio * 32767).astype(np.int16)
            yield seq, audio
            seq += 1


class StreamingServer:
    def __init__(self, streamer: TTSStreamer):
        self.streamer = streamer
        self.turns = {}  # turnId -> {"cancelled": bool, "seq": int}

    def wav_to_b64(self, audio: np.ndarray) -> str:
        import soundfile as sf
        buf = io.BytesIO()
        sf.write(buf, audio, SAMPLE_RATE, format="WAV", subtype="PCM_16")
        return base64.b64encode(buf.getvalue()).decode("ascii")

    async def handle_client(self, ws):
        log.info(f"Client: {ws.remote_address}")
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                if not isinstance(msg, dict):
                    continue
                await self.handle_message(ws, msg)
        except Exception:
            log.info("Client disconnected")

    async def handle_message(self, ws, msg: dict):
        mtype = msg.get("type")
        turn_id = msg.get("turnId", "default")

        if mtype == "turn_start":
            self.turns[turn_id] = {
                "cancelled": False,
                "text": "",
                "synthesizing": False,
                "pending": asyncio.Queue(),
            }
            log.info(f"Turn start: {turn_id}")

        elif mtype == "text_delta":
            turn = self.turns.get(turn_id)
            if not turn or turn["cancelled"]:
                return
            if msg.get("resync"):
                turn["text"] = msg.get("text", "")
            else:
                turn["text"] += msg.get("text", "")
            # True bi-streaming: kick off synthesis as soon as text arrives.
            # If a synthesis task is running, the new text waits in the
            # buffer and will be picked up in the next round.
            if not turn["synthesizing"] and turn["text"].strip():
                turn["synthesizing"] = True
                asyncio.create_task(self._streaming_loop(ws, turn_id))

        elif mtype == "turn_end":
            turn = self.turns.get(turn_id)
            if not turn:
                return
            # Mark end; the streaming loop will finish remaining text
            # then send turn_done.
            turn["ended"] = True
            if not turn["synthesizing"]:
                # No text ever arrived; just close the turn.
                if not turn["text"].strip():
                    await ws.send(json.dumps({"type": "turn_done", "turnId": turn_id}))
                    self.turns.pop(turn_id, None)
                else:
                    turn["synthesizing"] = True
                    asyncio.create_task(self._streaming_loop(ws, turn_id))

        elif mtype == "cancel":
            turn = self.turns.get(turn_id)
            if turn:
                turn["cancelled"] = True
            self.turns.pop(turn_id, None)
            log.info(f"Turn cancelled: {turn_id}")

    async def _streaming_loop(self, ws, turn_id: str):
        """Continuously synthesize buffered text until turn ends and
        buffer is drained. Each round synthesizes newly arrived text."""
        turn = self.turns.get(turn_id)
        if not turn:
            return
        try:
            seq = turn.get("seq", 0)
            synthesized_len = 0
            while True:
                if turn["cancelled"]:
                    break
                text = turn["text"]
                new_text = text[synthesized_len:].strip()
                if not new_text:
                    # No new text. If turn ended, we're done.
                    if turn.get("ended"):
                        break
                    # Wait a bit for more text.
                    await asyncio.sleep(0.2)
                    # Re-check turn still exists (cancel may have removed it)
                    if self.turns.get(turn_id) is not turn:
                        return
                    continue
                # Synthesize the new text chunk.
                log.info(f"Synthesizing chunk ({len(new_text)}ch, turn={turn_id})")
                chunk_seq = await self._synthesize_chunk(ws, turn_id, new_text, seq)
                seq += chunk_seq
                turn["seq"] = seq
                synthesized_len = len(text)
                # Loop: check for more text or turn end.

            if not turn["cancelled"]:
                await ws.send(json.dumps({"type": "turn_done", "turnId": turn_id}))
                log.info(f"Turn done: {turn_id} ({seq} chunks)")
        except Exception as e:
            log.error(f"Streaming loop error: {e}")
            try:
                await ws.send(json.dumps(
                    {"type": "error", "turnId": turn_id, "message": str(e)}))
            except Exception:
                pass
        finally:
            turn["synthesizing"] = False
            # Only pop if this turn object is still the current one
            if self.turns.get(turn_id) is turn and turn.get("ended"):
                self.turns.pop(turn_id, None)

    async def _synthesize_chunk(self, ws, turn_id: str, text: str, start_seq: int) -> int:
        """Synthesize one text chunk, stream audio chunks. Returns chunk count."""
        turn = self.turns.get(turn_id)
        loop = asyncio.get_event_loop()
        queue = asyncio.Queue()

        def _produce():
            try:
                for s, chunk in self.streamer.synthesize_stream(text):
                    if turn["cancelled"]:
                        break
                    loop.call_soon_threadsafe(queue.put_nowait, ("audio", chunk))
            except Exception as e:
                loop.call_soon_threadsafe(queue.put_nowait, ("error", e))
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, ("done", None))

        import threading
        t = threading.Thread(target=_produce, daemon=True)
        t.start()

        seq = start_seq
        while True:
            kind, payload = await queue.get()
            if kind == "done":
                break
            if kind == "error":
                raise payload
            if turn["cancelled"]:
                break
            b64 = self.wav_to_b64(payload)
            await ws.send(json.dumps({
                "type": "audio_chunk", "turnId": turn_id,
                "seq": seq, "data": b64, "format": "wav_24000",
            }))
            seq += 1
        return seq - start_seq

    async def run(self, host="127.0.0.1", port=18766):
        import websockets
        log.info(f"Listening on {host}:{port}")
        async with websockets.serve(
            self.handle_client, host, port, max_size=32 * 1024 * 1024
        ):
            await asyncio.Future()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=18766)
    p.add_argument("--model-dir", required=True)
    p.add_argument("--prompt-wav", required=True)
    p.add_argument("--prompt-text", required=True)
    p.add_argument("--fp16", action="store_true", default=True)
    a = p.parse_args()

    streamer = TTSStreamer(
        model_dir=a.model_dir,
        prompt_wav=a.prompt_wav,
        prompt_text=a.prompt_text,
        fp16=a.fp16,
    )
    server = StreamingServer(streamer)
    asyncio.run(server.run(a.host, a.port))


if __name__ == "__main__":
    main()
