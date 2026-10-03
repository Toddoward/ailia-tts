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
        # NOTE: ORT_ENABLE_ALL's extended fusions (e.g. SimplifiedLayerNormFusion)
        # crash on the fp16 CosyVoice3 backbone. BASIC keeps constant folding
        # without the problematic fusions.
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
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
        self.hift_f0_predictor = load('hift_f0_predictor_fp32.onnx')
        self.hift_source_generator = load('hift_source_generator_fp32.onnx')
        self.hift_decoder = load('hift_decoder_fp32.onnx')
        log.info("All models loaded!")

    def _prepare_prompt(self):
        log.info("Preparing voice prompt...")
        import librosa
        self.prompt_embedding = self._extract_speaker_embedding(str(PROMPT_WAV))
        self.prompt_speech_tokens = self._extract_speech_tokens(str(PROMPT_WAV))
        self.prompt_mel = self._extract_speech_mel(str(PROMPT_WAV))
        self.prompt_text = PROMPT_TEXT
        log.info(f"Voice prompt ready (emb={self.prompt_embedding.shape}, "
                 f"tokens={self.prompt_speech_tokens.shape}, mel={self.prompt_mel.shape})")

    def _extract_speaker_embedding(self, audio_path: str) -> np.ndarray:
        import librosa
        audio, _ = librosa.load(audio_path, sr=16000)
        audio = audio.astype(np.float32)
        mel = librosa.feature.melspectrogram(
            y=audio, sr=16000, n_fft=400, hop_length=160,
            n_mels=80, fmin=20, fmax=7600)
        log_mel = np.log(np.maximum(mel, 1e-10)).T
        log_mel = log_mel - log_mel.mean(axis=0, keepdims=True)
        feat = log_mel[np.newaxis, :, :].astype(np.float32)
        input_name = self.campplus.get_inputs()[0].name
        embedding = self.campplus.run(None, {input_name: feat})[0]
        return embedding.flatten()[np.newaxis, :].astype(np.float32)

    def _extract_speech_tokens(self, audio_path: str) -> np.ndarray:
        import librosa
        audio, _ = librosa.load(audio_path, sr=16000)
        audio = audio.astype(np.float32)
        mel = librosa.feature.melspectrogram(
            y=audio, sr=16000, n_fft=400, hop_length=160,
            n_mels=128, fmin=0, fmax=8000)
        log_mel = np.log10(np.maximum(mel, 1e-10))
        log_mel = np.maximum(log_mel, log_mel.max() - 8.0)
        log_mel = (log_mel + 4.0) / 4.0
        feat = log_mel[np.newaxis, :, :].astype(np.float32)
        feat_len = np.array([feat.shape[2]], dtype=np.int32)
        input_names = [inp.name for inp in self.speech_tokenizer.get_inputs()]
        tokens = self.speech_tokenizer.run(None, {
            input_names[0]: feat,
            input_names[1]: feat_len,
        })[0]
        return np.array(tokens, dtype=np.int64).reshape(1, -1)

    def _extract_speech_mel(self, audio_path: str) -> np.ndarray:
        import librosa
        audio, _ = librosa.load(audio_path, sr=24000)
        audio = audio.astype(np.float32)
        mel = librosa.feature.melspectrogram(
            y=audio, sr=24000, n_fft=1024, hop_length=256,
            n_mels=80, fmin=0, fmax=12000)
        log_mel = np.log(np.maximum(mel, 1e-10))
        return log_mel.T[np.newaxis, :, :].astype(np.float32)

    def _log_softmax(self, x: np.ndarray) -> np.ndarray:
        e = x - np.max(x)
        return e - np.log(np.sum(np.exp(e)))

    def _softmax(self, x: np.ndarray) -> np.ndarray:
        e = np.exp(x - np.max(x))
        return e / e.sum()

    def get_text_embedding(self, token_ids: np.ndarray) -> np.ndarray:
        return self.text_embedding.run(
            None, {'input_ids': token_ids.astype(np.int64)})[0]

    def get_speech_embedding(self, token_ids: np.ndarray) -> np.ndarray:
        return self.llm_speech_embedding.run(
            None, {'token': token_ids.astype(np.int64)})[0]

    def tokenize_text(self, text: str) -> np.ndarray:
        return np.array([self.tokenizer.encode(text, add_special_tokens=False)], dtype=np.int64)

    def synthesize(self, text: str) -> np.ndarray:
        """Synthesize text to int16 audio at 24kHz (blocking)."""
        speech_tokens = self._llm_inference(text)
        mel = self._flow_inference(
            speech_tokens,
            self.prompt_embedding,
            prompt_tokens=self.prompt_speech_tokens,
            prompt_mel=self.prompt_mel,
        )
        audio = self._hift_inference(mel)
        audio = np.clip(audio.squeeze(), -0.99, 0.99)
        return (audio * 32767).astype(np.int16)

    def _llm_inference(self, text: str, sampling_k: int = 25,
                       max_len: int = 500, min_len: int = 10) -> np.ndarray:
        """Generate speech tokens (zero-shot mode with prompt)."""
        pt = self.tokenize_text(self.prompt_text)
        tt = self.tokenize_text(text)
        combined = np.concatenate([pt, tt], axis=1)
        text_emb = self.get_text_embedding(combined)
        sos_emb = self.get_speech_embedding(np.array([[self.sos]], dtype=np.int64))
        task_emb = self.get_speech_embedding(np.array([[self.task_id]], dtype=np.int64))
        if self.prompt_speech_tokens is not None and self.prompt_speech_tokens.shape[1] > 0:
            prompt_speech_emb = self.get_speech_embedding(self.prompt_speech_tokens)
        else:
            prompt_speech_emb = np.zeros((1, 0, self.hidden_dim), dtype=np.float32)
        lm_input = np.concatenate(
            [sos_emb, text_emb, task_emb, prompt_speech_emb], axis=1).astype(np.float32)

        seq_len = lm_input.shape[1]
        attn = np.ones((1, seq_len), dtype=np.float32)
        out = self.llm_backbone_initial.run(
            None, {'inputs_embeds': lm_input, 'attention_mask': attn})
        hidden, past_kv = out[0], (out[1] if len(out) > 1 else None)
        logits = self.llm_decoder.run(None, {'hidden_state': hidden[:, -1:, :]})[0]

        tts_len = tt.shape[1]
        max_len = min(max_len, tts_len * 20)
        min_len = max(min_len, tts_len * 2)
        tokens = []
        for i in range(max_len):
            logp = self._log_softmax(logits.squeeze())
            top_k_idx = np.argsort(logp)[-sampling_k:]
            top_k_probs = self._softmax(logp[top_k_idx])
            tok = int(top_k_idx[np.random.choice(len(top_k_idx), p=top_k_probs)])
            if tok == self.eos_token and i >= min_len:
                break
            tokens.append(tok)
            emb = self.get_speech_embedding(np.array([[tok]], dtype=np.int64))
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
        return np.array([tokens], dtype=np.int64)

    def _flow_inference(self, speech_tokens: np.ndarray, embedding: np.ndarray,
                        prompt_tokens: np.ndarray = None,
                        prompt_mel: np.ndarray = None,
                        n_timesteps: int = 10) -> np.ndarray:
        """Speech tokens -> mel via conditional flow matching (Euler solver)."""
        from scipy.ndimage import zoom
        emb_norm = embedding / (np.linalg.norm(embedding, axis=1, keepdims=True) + 1e-8)
        spks = self.flow_speaker_projection.run(
            None, {'embedding': emb_norm.astype(np.float32)})[0]

        if prompt_tokens is not None and prompt_tokens.shape[1] > 0:
            all_tokens = np.concatenate([prompt_tokens, speech_tokens], axis=1)
            prompt_token_len = prompt_tokens.shape[1]
        else:
            all_tokens = speech_tokens
            prompt_token_len = 0

        token_embedded = self.flow_token_embedding.run(
            None, {'token': all_tokens.astype(np.int64)})[0]
        h = self.flow_pre_lookahead.run(
            None, {'token_embedded': token_embedded.astype(np.float32)})[0]

        token_mel_ratio = 2
        mel_len = h.shape[1]
        if prompt_tokens is not None and prompt_token_len > 0:
            mel_len1 = prompt_token_len * token_mel_ratio
        else:
            mel_len1 = 0

        conds = np.zeros((1, 80, mel_len), dtype=np.float32)
        if prompt_mel is not None and prompt_mel.shape[1] > 0 and mel_len1 > 0:
            prompt_mel_t = prompt_mel.transpose(0, 2, 1)
            src_len = prompt_mel_t.shape[2]
            if src_len != mel_len1:
                prompt_mel_t = zoom(prompt_mel_t, (1, 1, mel_len1 / src_len), order=1)
            conds[:, :, :mel_len1] = prompt_mel_t[:, :, :mel_len1]

        mu = h.transpose(0, 2, 1).astype(np.float32)
        mask = np.ones((1, 1, mel_len), dtype=np.float32)
        x = np.random.randn(1, 80, mel_len).astype(np.float32)

        x_b = np.concatenate([x, x], axis=0)
        mask_b = np.concatenate([mask, mask], axis=0)
        mu_b = np.concatenate([mu, mu], axis=0)
        spks_b = np.concatenate([spks, spks], axis=0)
        conds_b = np.concatenate([conds, conds], axis=0)

        log.info(f"  Flow: {n_timesteps} steps (mel_len={mel_len}, prompt={mel_len1})")
        dt = 1.0 / n_timesteps
        for step in range(n_timesteps):
            t = np.array([step / n_timesteps, step / n_timesteps], dtype=np.float32)
            velocity = self.flow_decoder.run(None, {
                'x': x_b, 'mask': mask_b, 'mu': mu_b,
                't': t, 'spks': spks_b, 'cond': conds_b,
            })[0]
            x_b = x_b + velocity * dt

        mel = x_b[:1]
        if mel_len1 > 0:
            mel = mel[:, :, mel_len1:]
        return mel.astype(np.float32)

    def _stift(self, x: np.ndarray, n_fft: int = 16, hop_len: int = 4) -> tuple:
        from scipy.signal import get_window
        window = get_window("hann", n_fft, fftbins=True).astype(np.float32)
        x = x.astype(np.float32)
        pad = n_fft // 2
        x = np.pad(x, (pad, pad), mode='reflect')
        n_frames = 1 + (len(x) - n_fft) // hop_len
        n_freqs = n_fft // 2 + 1
        real = np.zeros((n_freqs, n_frames), dtype=np.float32)
        imag = np.zeros((n_freqs, n_frames), dtype=np.float32)
        for i in range(n_frames):
            frame = x[i * hop_len:i * hop_len + n_fft] * window
            spec = np.fft.rfft(frame)
            real[:, i] = np.real(spec)
            imag[:, i] = np.imag(spec)
        return real, imag

    def _istft(self, magnitude: np.ndarray, phase: np.ndarray,
               n_fft: int = 16, hop_len: int = 4) -> np.ndarray:
        from scipy.signal import get_window
        window = get_window("hann", n_fft, fftbins=True).astype(np.float32)
        magnitude = np.clip(magnitude, a_min=None, a_max=100.0)
        spec = magnitude * np.exp(1j * phase)
        n_frames = spec.shape[1]
        out_len = n_fft + (n_frames - 1) * hop_len
        audio = np.zeros(out_len, dtype=np.float32)
        wsum = np.zeros(out_len, dtype=np.float32)
        for i in range(n_frames):
            frame = np.fft.irfft(spec[:, i], n=n_fft).astype(np.float32)
            s = i * hop_len
            audio[s:s + n_fft] += frame * window
            wsum[s:s + n_fft] += window ** 2
        return (audio / np.maximum(wsum, 1e-8)).astype(np.float32)

    def _hift_inference(self, mel: np.ndarray) -> np.ndarray:
        """Mel -> waveform via HiFT vocoder."""
        f0 = self.hift_f0_predictor.run(None, {'mel': mel.astype(np.float32)})[0]
        f0_input = f0[:, np.newaxis, :].astype(np.float32)
        source = self.hift_source_generator.run(None, {'f0': f0_input})[0]
        stft_r, stft_i = self._stift(source.squeeze(), n_fft=16, hop_len=4)
        source_stft = np.concatenate([stft_r, stft_i], axis=0)[np.newaxis, :, :]
        outputs = self.hift_decoder.run(None, {
            'mel': mel.astype(np.float32),
            'source_stft': source_stft.astype(np.float32),
        })
        magnitude, phase = outputs[0], outputs[1]
        audio = self._istft(magnitude.squeeze(0), phase.squeeze(0), n_fft=16, hop_len=4)
        return np.clip(audio, -0.99, 0.99).astype(np.float32)


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
