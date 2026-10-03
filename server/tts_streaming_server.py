#!/usr/bin/env python3
"""
Ailia TTS - Local Streaming Server (CosyVoice3)
Bi-streaming WebSocket server: text deltas in, audio chunks out.

Protocol:
  Client -> Server:
    {"type": "turn_start", "turnId": str, "voice": str}
    {"type": "text_delta", "turnId": str, "text": str}
    {"type": "turn_end", "turnId": str}
    {"type": "cancel", "turnId": str}

  Server -> Client:
    {"type": "audio_chunk", "turnId": str, "seq": int, "data": str (b64 wav), "format": "wav_24000"}
    {"type": "turn_done", "turnId": str}
    {"type": "error", "turnId": str, "message": str}
"""

import argparse
import asyncio
import base64
import io
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import websockets

logging.basicConfig(level=logging.INFO, format='[tts] %(message)s')
log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
MODEL_DIR = BASE_DIR / "models"
SAMPLE_RATE = 24000
PROMPT_WAV = BASE_DIR / "ailia_prompt.wav"
PROMPT_TEXT = "안녕하세요, 저는 에일리아예요. 주인님을 위해 목소리를 내고 있어요."

executor = ThreadPoolExecutor(max_workers=2)


class CosyVoice3Streaming:
    """CosyVoice3 ONNX inference."""

    def __init__(self, model_dir: Path):
        self.model_dir = model_dir
        self.sample_rate = SAMPLE_RATE
        self.hidden_dim = 896
        self.speech_token_size = 6561
        self.sos = self.speech_token_size + 0
        self.eos_token = self.speech_token_size + 1
        self.task_id = self.speech_token_size + 2
        self._load_tokenizer()
        self._load_onnx_models()
        self._prepare_prompt()

    def _load_tokenizer(self):
        log.info("Loading tokenizer...")
        from transformers import AutoTokenizer
        self.tokenizer = AutoTokenizer.from_pretrained(str(self.model_dir), trust_remote_code=True)
        log.info("Tokenizer loaded")

    def _load_onnx_models(self):
        import onnxruntime as ort
        log.info("Loading ONNX models...")
        so = ort.SessionOptions()
        so.log_severity_level = 3
        providers = ['CPUExecutionProvider']
        d = str(self.model_dir)
        def load(name):
            log.info(f"  {name}...")
            return ort.InferenceSession(os.path.join(d, name), so, providers=providers)
        self.text_embedding = load('text_embedding_fp32.onnx')
        self.campplus = load('campplus.onnx')
        self.speech_tokenizer = load('speech_tokenizer_v3.onnx')
        self.llm_backbone_initial = load('llm_backbone_initial_fp16.onnx')
        self.llm_backbone_decode = load('llm_backbone_decode_fp16.onnx')
        self.llm_decoder = load('llm_decoder_fp16.onnx')
        self.llm_speech_embedding = load('llm_speech_embedding_fp16.onnx')
        self.flow_token_embedding = load('flow_token_embedding_fp16.onnx')
        self.flow_pre_lookahead = load('flow_pre_lookahead_fp16.onnx')
        self.flow_speaker_projection = load('flow_speaker_projection_fp16.onnx')
        self.flow_decoder = load('flow.decoder.estimator.fp16.onnx')
        self.hift_decoder = load('hift_decoder_fp32.onnx')
        log.info("All models loaded!")

    def _prepare_prompt(self):
        log.info("Preparing voice prompt...")
        import librosa
        import soundfile as sf
        wav, sr = sf.read(str(PROMPT_WAV))
        if sr != 16000:
            wav = librosa.resample(wav, orig_sr=sr, target_sr=16000)
        mel = librosa.feature.melspectrogram(y=wav, sr=16000, n_mels=80)
        mel = np.log(mel + 1e-6).T[np.newaxis, :, :].astype(np.float32)
        self.prompt_embedding = self.campplus.run(None, {'input': mel})[0]
        self.prompt_text = PROMPT_TEXT
        log.info("Voice prompt ready")

    def tokenize_text(self, text: str) -> np.ndarray:
        return np.array([self.tokenizer.encode(text, add_special_tokens=False)], dtype=np.int64)

    def synthesize(self, text: str) -> np.ndarray:
        """Synthesize text to int16 audio at 24kHz (blocking)."""
        # LLM: text -> speech tokens
        pt = self.tokenize_text(self.prompt_text)
        tt = self.tokenize_text(text)
        combined = np.concatenate([pt, tt], axis=1)
        text_emb = self.text_embedding.run(None, {'input_ids': combined.astype(np.int64)})[0]
        sos_emb = self.llm_speech_embedding.run(None, {'token': np.array([[self.sos]], dtype=np.int64)})[0]
        task_emb = self.llm_speech_embedding.run(None, {'token': np.array([[self.task_id]], dtype=np.int64)})[0]
        lm_input = np.concatenate([sos_emb, text_emb, task_emb], axis=1).astype(np.float32)
        seq_len = lm_input.shape[1]
        attn = np.ones((1, seq_len), dtype=np.float32)
        out = self.llm_backbone_initial.run(None, {'inputs_embeds': lm_input, 'attention_mask': attn})
        hidden, past_kv = out[0], (out[1] if len(out) > 1 else None)
        logits = self.llm_decoder.run(None, {'hidden_state': hidden[:, -1:, :]})[0]

        tts_len = tt.shape[1]
        max_len = min(500, tts_len * 20)
        min_len = max(10, tts_len * 2)
        tokens = []
        for i in range(max_len):
            tok = int(np.argmax(logits.squeeze()))
            if tok == self.eos_token and i >= min_len:
                break
            tokens.append(tok)
            emb = self.llm_speech_embedding.run(None, {'token': np.array([[tok]], dtype=np.int64)})[0]
            attn = np.ones((1, seq_len + len(tokens)), dtype=np.float32)
            inp = {'inputs_embeds': emb.astype(np.float32), 'attention_mask': attn}
            if past_kv is not None:
                inp['past_key_values'] = past_kv
            out = self.llm_backbone_decode.run(None, inp)
            hidden = out[0]
            if len(out) > 1:
                past_kv = out[1]
            logits = self.llm_decoder.run(None, {'hidden_state': hidden})[0]

        log.info(f"  Generated {len(tokens)} speech tokens")
        speech_tokens = np.array([tokens], dtype=np.int64)

        # Flow: tokens -> mel
        emb = self.prompt_embedding
        emb_norm = emb / (np.linalg.norm(emb, axis=1, keepdims=True) + 1e-8)
        spks = self.flow_speaker_projection.run(None, {'embedding': emb_norm.astype(np.float32)})[0]
        tok_emb = self.flow_token_embedding.run(None, {'token': speech_tokens.astype(np.int64)})[0]
        h = self.flow_pre_lookahead.run(None, {'token_embedded': tok_emb.astype(np.float32)})[0]
        mel = self.flow_decoder.run(None, {
            'x': np.random.randn(1, 80, h.shape[1] * 2).astype(np.float32),
            'spks': spks.astype(np.float32),
            'h': h.astype(np.float32),
        })[0]

        # HiFT: mel -> audio
        audio = self.hift_decoder.run(None, {'mel': mel.astype(np.float32)})[0]
        audio = np.clip(audio.squeeze(), -1, 1)
        return (audio * 32767).astype(np.int16)


class StreamingServer:
    def __init__(self, model_dir: Path):
        self.model_dir = model_dir
        self.tts = None
        self.turns = {}

    async def load(self):
        log.info("Loading CosyVoice3...")
        loop = asyncio.get_event_loop()
        self.tts = await loop.run_in_executor(executor, CosyVoice3Streaming, self.model_dir)
        log.info("CosyVoice3 ready!")

    def wav_to_b64(self, audio: np.ndarray) -> str:
        import soundfile as sf
        buf = io.BytesIO()
        sf.write(buf, audio, SAMPLE_RATE, format='WAV', subtype='PCM_16')
        return base64.b64encode(buf.getvalue()).decode('ascii')

    async def synthesize_and_stream(self, ws, turn_id: str, text: str):
        turn = self.turns.get(turn_id)
        if not turn or turn["cancelled"]:
            return
        try:
            loop = asyncio.get_event_loop()
            start = time.time()
            audio = await loop.run_in_executor(executor, self.tts.synthesize, text)
            elapsed = time.time() - start
            log.info(f"Synth {len(text)}ch -> {len(audio)/SAMPLE_RATE:.1f}s in {elapsed:.1f}s")
            if turn.get("cancelled"):
                return
            chunk_n = SAMPLE_RATE  # 1s chunks
            seq = turn["seq"]
            for i in range(0, len(audio), chunk_n):
                if turn.get("cancelled"):
                    break
                b64 = self.wav_to_b64(audio[i:i+chunk_n])
                await ws.send(json.dumps({
                    "type": "audio_chunk", "turnId": turn_id,
                    "seq": seq, "data": b64, "format": "wav_24000"}))
                seq += 1
            turn["seq"] = seq
        except Exception as e:
            log.error(f"Synthesis error: {e}")
            await ws.send(json.dumps({"type": "error", "turnId": turn_id, "message": str(e)}))

    async def handle_client(self, ws):
        log.info(f"Client: {ws.remote_address}")
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except:
                    continue
                await self.handle_message(ws, msg)
        except websockets.exceptions.ConnectionClosed:
            log.info("Client disconnected")

    async def handle_message(self, ws, msg: dict):
        mtype = msg.get("type")
        turn_id = msg.get("turnId", "default")
        if mtype == "turn_start":
            self.turns[turn_id] = {"buffer": "", "seq": 0, "cancelled": False}
            log.info(f"Turn start: {turn_id}")
        elif mtype == "text_delta":
            turn = self.turns.get(turn_id)
            if not turn or turn["cancelled"]:
                return
            if msg.get("resync"):
                turn["buffer"] = msg.get("text", "")
            else:
                turn["buffer"] += msg.get("text", "")
            buf = turn["buffer"]
            for delim in ['.', '!', '?', '\n']:
                idx = buf.rfind(delim)
                if idx > 20:
                    seg = buf[:idx+1].strip()
                    turn["buffer"] = buf[idx+1:]
                    if seg:
                        asyncio.create_task(self.synthesize_and_stream(ws, turn_id, seg))
                    break
        elif mtype == "turn_end":
            turn = self.turns.get(turn_id)
            if not turn or turn["cancelled"]:
                return
            if turn["buffer"].strip():
                await self.synthesize_and_stream(ws, turn_id, turn["buffer"].strip())
            await ws.send(json.dumps({"type": "turn_done", "turnId": turn_id}))
            self.turns.pop(turn_id, None)
            log.info(f"Turn done: {turn_id}")
        elif mtype == "cancel":
            turn = self.turns.get(turn_id)
            if turn:
                turn["cancelled"] = True
            self.turns.pop(turn_id, None)

    async def run(self, host="127.0.0.1", port=18766):
        await self.load()
        log.info(f"Listening on {host}:{port}")
        async with websockets.serve(self.handle_client, host, port, max_size=32*1024*1024):
            await asyncio.Future()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=18766)
    p.add_argument("--model-dir", default=str(MODEL_DIR))
    a = p.parse_args()
    asyncio.run(StreamingServer(Path(a.model_dir)).run(a.host, a.port))
