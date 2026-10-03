# Ailia TTS — Local Realtime Bi-Streaming

Muse AI의 답변을 실시간 음성으로 읽어주는 로컬 TTS 시스템입니다.

## 아키텍처

```
Chrome 확장 (DOM 관측 → 텍스트 스트리밍)
    ↕ WebSocket (localhost:18766)
로컬 TTS 서버 (CosyVoice3 → 오디오 스트리밍)
    ↕
Chrome 확장 (오디오 재생)
```

**Bi-Streaming**: 텍스트가 들어오는 대로 음성이 나갑니다. 문장이 끝날 때까지 기다리지 않아요.

## 구성 요소

### 1. 로컬 TTS 서버 (`server/`)
- `tts_streaming_server.py` — WebSocket 서버 (포트 18766)
- `ailia_prompt.wav` — 에일리아 음성 프롬프트 (F1 클로닝)
- CosyVoice3 ONNX 모델 (설치 스크립트가 자동 다운로드, ~2.9GB)

**모델**: FunAudioLLM CosyVoice3-0.5B (ayousanz ONNX fp16 양자화)
- Bi-streaming 지원 (150ms 지연)
- 한국어/영어 포함 9개 언어
- 감정/스타일 제어 (instruct)

### 2. Chrome 확장 (`extension/` — v0.2.2)
- `src/content.js` — DOM 관측, 텍스트 델타 스트리밍 (청킹 없음!)
- `src/background.js` — localhost WebSocket 직접 연결
- `src/offscreen.js` — 오디오 재생
- `src/popup.html/js` — 서버 URL 설정 + 연결 테스트

### 3. 설치 & 실행 (`install/`)
- `install.sh` / `install.bat` — 최초 설치 + 업데이트 (재실행 안전)
- `run_server.sh` / `run_server.bat` — **서버 실행 (권장)**
  - 미설치 시 자동으로 install 실행
  - 레포 버전이 설치된 버전보다 새로우면 자동 업데이트 후 실행
  - 실행 전 `server/requirements.txt` 기준으로 패키지 검증 (부족하면 자동 설치)

### 4. Python 의존성 (`server/requirements.txt`)
- `onnxruntime`, `numpy`, `websockets`, `transformers`, `librosa`, `soundfile`
- install과 run_server 모두 이 파일을 기준으로 설치/검증합니다

## 빠른 시작

### 1. 레포 클론 (최초 1회)
```bash
git clone https://github.com/<your-org>/ailia-tts-local.git
cd ailia-tts-local
```

### 2. 서버 실행
```bash
# Linux / macOS
./install/run_server.sh

# Windows (더블클릭 또는 PowerShell)
install\run_server.bat
```

`run_server`가 알아서 설치하고, 업데이트가 있으면 최신 버전으로 갱신한 뒤 서버를 시작합니다.

### 3. Chrome 확장 설치
1. `chrome://extensions` 접속
2. 개발자 모드 활성화
3. "압축해제된 확장 프로그램 로드" → `extension/` 폴더 선택
4. 툴바 아이콘 클릭 → 서버 URL 확인 (기본: ws://127.0.0.1:18766)
5. "연결 테스트" 버튼으로 확인

## 업데이트 방법

```bash
git pull                    # 최신 코드 받기
./install/run_server.sh     # 또는 install\run_server.bat
```

`run_server`가 VERSION을 비교해서 자동으로 install을 다시 실행합니다.
수동으로 강제 재설치가 필요하면 `install/install.sh` (또는 `install.bat`)를 직접 실행하세요.

## 수동 설치 (고급)

```bash
# Linux / macOS
chmod +x install/install.sh
./install/install.sh

# Windows
install\install.bat
```

## 프로토콜 (Bi-Streaming)

**확장 → 서버:**
```json
{"type": "turn_start", "turnId": "turn-1-..."}
{"type": "text_delta", "turnId": "...", "text": "안녕하세요"}
{"type": "text_delta", "turnId": "...", "text": ", 주인님!"}
{"type": "turn_end", "turnId": "..."}
```

**서버 → 확장:**
```json
{"type": "audio_chunk", "turnId": "...", "seq": 0, "data": "base64...", "format": "wav_24000"}
{"type": "audio_chunk", "turnId": "...", "seq": 1, "data": "base64..."}
{"type": "turn_done", "turnId": "..."}
```

## 설치 위치

| OS | 경로 |
|---|---|
| Linux / macOS | `~/.ailia-tts/` |
| Windows | `%USERPROFILE%\.ailia-tts\` |

- `venv/` — Python 가상환경
- `models/` — CosyVoice3 ONNX 모델 (~2.9GB)
- `tts_streaming_server.py` — 서버 (레포 버전으로 자동 동기화)
- `ailia_prompt.wav` — 음성 프롬프트
- `VERSION` — 설치된 버전

## 시스템 요구사항

- **RAM**: 8GB+ 권장 (모델 2.9GB + 추론 여유)
- **디스크**: 4GB+ 여유
- **Python**: 3.10+
- **OS**: Windows 10+, macOS 12+, Linux (x86_64)

## v0.1.x (Supabase 릴레이)와의 차이점

| | v0.1.x | v0.2.x |
|---|---|---|
| 연결 | Supabase 릴레이 | localhost 직접 |
| 지연 | ~5초 | ~1-2초 목표 |
| 모델 | Supertonic 3 (VM) | CosyVoice3 (로컬) |
| 청킹 | 문장 단위 | 스트리밍 (청킹 없음) |
| 설정 | 페어링 코드 필요 | URL만 입력 |
| 개인정보 | 음성이 클라우드 경유 | 완전 로컬 |

## 라이선스

- CosyVoice3: Apache 2.0
- 본 프로젝트: 비영리 오픈소스
