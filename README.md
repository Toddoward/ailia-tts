# Ailia TTS v3

Real-time voice for Muse AI responses. Zero-base rebuild.

## Architecture

```
[Chrome Extension] --WebSocket--> [Python Server] --> [Speaker]
  text capture (DOM)               CosyVoice3          audio playback
  audio playback                   official PyTorch
```

## What's New in v3

- **Official CosyVoice3** (`FunAudioLLM/Fun-CosyVoice3-0.5B-2512`) via PyTorch
- **True bi-streaming**: synthesis starts on first `text_delta`, no sentence buffering
- **GPU required**: CUDA for real-time performance
- **~100 lines** server core (vs 474 lines of hand-rolled ONNX)

## Quick Start (Windows)

1. Place your voice prompt as `prompt.wav` in the install directory
2. Run `install/install.bat`
3. Run `install/run_server.bat`
4. Load `extension/` in Chrome (Developer Mode → Load Unpacked)
5. Open claude.ai and chat — you'll hear Ailia's voice

## Protocol

Client → Server:
- `{"type": "turn_start", "turnId": str}`
- `{"type": "text_delta", "turnId": str, "text": str, "resync"?: bool}`
- `{"type": "turn_end", "turnId": str}`
- `{"type": "cancel", "turnId": str}`

Server → Client:
- `{"type": "audio_chunk", "turnId": str, "seq": int, "data": str (b64 WAV), "format": "wav_24000"}`
- `{"type": "turn_done", "turnId": str}`
- `{"type": "error", "turnId": str, "message": str}`

## Requirements

- Python 3.10+
- NVIDIA GPU with CUDA 12.1+
- ~10GB disk (PyTorch + model)
- Chrome (for extension)

## Project Structure

```
v3/
  server/tts_server.py      # Thin WebSocket wrapper (~200 lines)
  extension/                # Chrome MV3 extension
    src/content.js          # DOM text capture
    src/background.js       # Message router
    src/offscreen.js        # WebSocket + audio playback
  install/                  # Setup scripts
    install.bat / install.sh
    run_server.bat / run_server.sh
```
