// Ailia TTS — offscreen document (MV3)
// Owns the WebSocket to the TTS server AND audio playback.
// The service worker just routes content-script messages here.
// WebSocket lives here (not in the service worker) because MV3 service
// workers are terminated aggressively, which drops in-memory queues.

const VERSION = '0.2.4';
let TTS_WS_URL = 'ws://127.0.0.1:18766';
let VOICE = 'F1';

function log(...args) { console.log('[ailia-tts][offscreen]', ...args); }
function warn(...args) { console.warn('[ailia-tts][offscreen]', ...args); }
function err(...args) { console.error('[ailia-tts][offscreen]', ...args); }

// --- WebSocket to TTS server --------------------------------------------

let ws = null;
let wsReady = false;
let reconnectTimer = null;
const outboundQueue = [];

function connect() {
  if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) {
    return;
  }
  log('connecting to TTS server:', TTS_WS_URL);
  wsReady = false;
  try {
    ws = new WebSocket(TTS_WS_URL);
  } catch (e) {
    err('WebSocket creation failed:', e.message);
    scheduleReconnect();
    return;
  }
  ws.onopen = () => {
    log('TTS WebSocket OPEN');
    wsReady = true;
    flushOutboundQueue();
  };
  ws.onmessage = (ev) => {
    let msg;
    try { msg = JSON.parse(ev.data); } catch (_) { return; }
    handleServerMessage(msg);
  };
  ws.onclose = () => {
    warn('TTS WebSocket CLOSED, will retry');
    wsReady = false;
    ws = null;
    scheduleReconnect();
  };
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connect();
  }, 3000);
}

function sendToServer(obj) {
  const raw = JSON.stringify(obj);
  if (wsReady && ws && ws.readyState === WebSocket.OPEN) {
    try {
      ws.send(raw);
    } catch (e) {
      warn('ws.send failed, queueing:', e.message);
      outboundQueue.push(raw);
      wsReady = false;
      scheduleReconnect();
    }
  } else {
    log('TTS not ready, queueing:', obj.type);
    outboundQueue.push(raw);
    connect();
  }
}

function flushOutboundQueue() {
  if (!outboundQueue.length) return;
  log(`flushing ${outboundQueue.length} queued message(s)`);
  while (outboundQueue.length && wsReady && ws && ws.readyState === WebSocket.OPEN) {
    try {
      ws.send(outboundQueue.shift());
    } catch (e) {
      warn('flush send failed:', e.message);
      break;
    }
  }
}

function handleServerMessage(msg) {
  const type = msg.type;
  if (type === 'audio_chunk') {
    queueAudioChunk(msg);
  } else if (type === 'turn_done') {
    log('turn done:', msg.turnId);
  } else if (type === 'error') {
    err('TTS server error:', msg.turnId, msg.message);
  }
}

// --- Audio playback ------------------------------------------------------

// Per-turn buffers: turnId -> { expectedSeq, buffer: Map(seq -> item), playing }
const turns = new Map();
let currentAudio = null;
let activeTurnId = null;

function b64ToBlob(b64, mime) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new Blob([bytes], { type: mime });
}

function getTurn(turnId) {
  if (!turns.has(turnId)) {
    turns.set(turnId, { expectedSeq: 0, buffer: new Map(), playing: false });
  }
  return turns.get(turnId);
}

async function pumpTurn(turnId) {
  const turn = turns.get(turnId);
  if (!turn || turn.playing) return;
  if (activeTurnId && activeTurnId !== turnId) return;

  const item = turn.buffer.get(turn.expectedSeq);
  if (!item) return;

  turn.buffer.delete(turn.expectedSeq);
  turn.expectedSeq++;
  turn.playing = true;
  activeTurnId = turnId;

  currentAudio = new Audio();
  currentAudio.src = URL.createObjectURL(b64ToBlob(item.audio, 'audio/wav'));

  currentAudio.onended = () => {
    URL.revokeObjectURL(currentAudio.src);
    currentAudio = null;
    turn.playing = false;
    if (activeTurnId === turnId) activeTurnId = null;
    pumpTurn(turnId);
    for (const [tid] of turns) {
      if (tid !== turnId) pumpTurn(tid);
    }
  };
  currentAudio.onerror = () => {
    err('playback error for turn:', turnId, 'seq:', item.seq);
    currentAudio = null;
    turn.playing = false;
    if (activeTurnId === turnId) activeTurnId = null;
    pumpTurn(turnId);
  };
  try {
    log(`playing turn ${turnId} seq ${item.seq}`);
    await currentAudio.play();
  } catch (e) {
    err('play() failed:', e.message);
    turn.playing = false;
    if (activeTurnId === turnId) activeTurnId = null;
    pumpTurn(turnId);
  }
}

function queueAudioChunk({ turnId, seq, data, format }) {
  seq = seq ?? 0;
  log(`received audio chunk turn ${turnId} seq ${seq} (${(data || '').length} chars)`);
  const turn = getTurn(turnId);
  if (seq < turn.expectedSeq || turn.buffer.has(seq)) {
    log(`duplicate/old seq ${seq}, skipping`);
    return;
  }
  turn.buffer.set(seq, { audio: data, format: format || 'wav_24000', seq });
  if (turn.buffer.size > 30) {
    const oldest = Math.min(...turn.buffer.keys());
    turn.buffer.delete(oldest);
  }
  pumpTurn(turnId);
}

function stopTurn(turnId) {
  log('stop requested for turn:', turnId);
  turns.delete(turnId);
  if (activeTurnId === turnId && currentAudio) {
    currentAudio.pause();
    URL.revokeObjectURL(currentAudio.src);
    currentAudio = null;
    activeTurnId = null;
  }
  for (const [tid] of turns) pumpTurn(tid);
}

// --- Messages from background (routed from content script) ---------------

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.source === 'ailia-tts-bg-config') {
    if (msg.ttsServerUrl && msg.ttsServerUrl !== TTS_WS_URL) {
      TTS_WS_URL = msg.ttsServerUrl;
      log('server URL updated:', TTS_WS_URL);
      if (ws) { try { ws.close(); } catch (_) {} ws = null; }
      wsReady = false;
      connect();
    }
    if (msg.voice) VOICE = msg.voice;
    return;
  }

  if (msg.source !== 'ailia-tts-bg') return;

  if (msg.type === 'test_audio') {
    // Ask the server to synthesize (default or custom test sentence)
    // and stream the audio back for playback.
    const turnId = `test-audio-${Date.now()}`;
    log('test_audio requested, turn:', turnId);
    const out = { type: 'test_audio', turnId };
    if (msg.text) out.text = msg.text;
    sendToServer(out);
    return;
  }

  if (msg.type === 'test_text') {
    // Stream a test sentence to the server in small chunks with delays,
    // simulating real token streaming. Server logs receipt.
    const text = msg.text || 'test';
    const turnId = `test-text-${Date.now()}`;
    log('test_text requested, turn:', turnId, `(${text.length} chars)`);
    sendToServer({ type: 'turn_start', turnId, voice: VOICE });
    // Split into ~8 char chunks, 120ms apart
    const chunks = [];
    for (let i = 0; i < text.length; i += 8) chunks.push(text.slice(i, i + 8));
    chunks.forEach((chunk, i) => {
      setTimeout(() => {
        sendToServer({ type: 'text_delta', turnId, text: chunk });
        if (i === chunks.length - 1) {
          setTimeout(() => sendToServer({ type: 'turn_end', turnId }), 150);
        }
      }, i * 120);
    });
    return;
  }

  if (msg.type === 'turn_start') {
    sendToServer({ type: 'turn_start', turnId: msg.turnId, voice: VOICE });
  } else if (msg.type === 'text_delta') {
    const out = { type: 'text_delta', turnId: msg.turnId, text: msg.text };
    if (msg.resync) out.resync = true;
    sendToServer(out);
  } else if (msg.type === 'turn_end') {
    sendToServer({ type: 'turn_end', turnId: msg.turnId });
  } else if (msg.type === 'cancel') {
    sendToServer({ type: 'cancel', turnId: msg.turnId });
    stopTurn(msg.turnId);
  }
});

// Notify background that we're ready.
chrome.runtime.sendMessage({ source: 'ailia-tts-offscreen', type: 'offscreenReady' });
log(`offscreen v${VERSION} ready — WebSocket owner`);

// Proactively connect so the socket is warm when the first turn starts.
connect();
