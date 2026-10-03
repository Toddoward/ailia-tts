// Ailia TTS v3 - Offscreen Document
// Owns the WebSocket connection and audio playback.
const VERSION = '0.2.6';
console.log(`[ailia-tts] offscreen v${VERSION}`);

const WS_URL = 'ws://127.0.0.1:18766';
let ws = null;
let reconnectTimer = null;
let audioQueue = [];
let isPlaying = false;
let audioCtx = null;

function getAudioCtx() {
  if (!audioCtx) {
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  }
  if (audioCtx.state === 'suspended') audioCtx.resume();
  return audioCtx;
}

function connect() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    return;
  }
  console.log('[ailia-tts] connecting to', WS_URL);
  ws = new WebSocket(WS_URL);

  ws.onopen = () => {
    console.log('[ailia-tts] WebSocket connected');
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
  };

  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      handleServerMessage(msg);
    } catch (e) {
      console.error('[ailia-tts] bad message:', e);
    }
  };

  ws.onclose = () => {
    console.log('[ailia-tts] WebSocket closed, retrying in 3s');
    scheduleReconnect();
  };

  ws.onerror = () => {
    ws.close();
  };
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connect();
  }, 3000);
}

function handleServerMessage(msg) {
  switch (msg.type) {
    case 'audio_chunk':
      enqueueAudio(msg.data);
      break;
    case 'turn_done':
      console.log(`[ailia-tts] turn done: ${msg.turnId}`);
      break;
    case 'error':
      console.error(`[ailia-tts] server error: ${msg.message}`);
      break;
  }
}

function b64ToArrayBuffer(b64) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes.buffer;
}

async function enqueueAudio(b64Wav) {
  try {
    const ctx = getAudioCtx();
    const buf = b64ToArrayBuffer(b64Wav);
    const audioBuf = await ctx.decodeAudioData(buf.slice(0));
    audioQueue.push(audioBuf);
    pumpAudio();
  } catch (e) {
    console.error('[ailia-tts] audio decode failed:', e);
  }
}

function pumpAudio() {
  if (isPlaying || audioQueue.length === 0) return;
  isPlaying = true;
  const ctx = getAudioCtx();
  const buf = audioQueue.shift();
  const src = ctx.createBufferSource();
  src.buffer = buf;
  src.connect(ctx.destination);
  src.onended = () => {
    isPlaying = false;
    pumpAudio();
  };
  src.start();
}

// Handle messages from content/background
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg._routed && ws && ws.readyState === WebSocket.OPEN) {
    // Forward turn/text messages to server
    const { _routed, source, ...clean } = msg;
    ws.send(JSON.stringify(clean));
  } else if (msg._routed) {
    console.warn('[ailia-tts] WS not connected, dropping message');
  }
  return false;
});

// Test helpers for popup
chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === 'test_connect') connect();
});

// Auto-connect on load
connect();

// Keepalive
setInterval(() => chrome.runtime.connect({ name: 'keepalive' }), 20000);
