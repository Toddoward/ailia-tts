// Ailia TTS — background service worker (MV3) v0.2.0
// Localhost streaming mode: direct WebSocket to local TTS server.
// Bi-streaming protocol: text deltas out, audio chunks in.

const VERSION = '0.2.0';
const TTS_WS_URL = 'ws://127.0.0.1:18766';

let ws = null;
let wsReady = false;
let reconnectTimer = null;
let settings = null;

// Pending outbound queue (when WS not ready)
const outboundQueue = [];

// Audio chunk reassembly is handled by offscreen (streaming playback)
// Pending turns: turnId -> { seq }
const turnSeqs = new Map();

// Offscreen readiness
let offscreenReady = false;
const audioQueue = [];

function log(...args) { console.log('[ailia-tts][bg]', ...args); }
function warn(...args) { console.warn('[ailia-tts][bg]', ...args); }
function err(...args) { console.error('[ailia-tts][bg]', ...args); }

async function loadSettings() {
  const s = await chrome.storage.sync.get({
    ttsServerUrl: TTS_WS_URL,
    voice: 'F1',
    enabled: true,
  });
  settings = s;
  log('settings loaded:', { enabled: s.enabled, voice: s.voice, serverUrl: s.ttsServerUrl });
  return s;
}

function connect() {
  if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) {
    return;
  }
  const url = (settings && settings.ttsServerUrl) || TTS_WS_URL;
  log('connecting to local TTS server:', url);
  wsReady = false;

  try {
    ws = new WebSocket(url);
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

  ws.onerror = () => {
    // onclose will follow
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
    ws.send(raw);
  } else {
    log('TTS not ready, queueing:', obj.type);
    outboundQueue.push(raw);
    connect(); // ensure connection attempt
  }
}

function flushOutboundQueue() {
  if (!outboundQueue.length) return;
  log(`flushing ${outboundQueue.length} queued message(s)`);
  while (outboundQueue.length && wsReady && ws && ws.readyState === WebSocket.OPEN) {
    ws.send(outboundQueue.shift());
  }
}

function handleServerMessage(msg) {
  const type = msg.type;
  if (type === 'audio_chunk') {
    handleAudioChunk(msg);
  } else if (type === 'turn_done') {
    log('turn done:', msg.turnId);
    turnSeqs.delete(msg.turnId);
  } else if (type === 'error') {
    err('TTS server error:', msg.turnId, msg.message);
  }
}

async function handleAudioChunk({ turnId, seq, data, format }) {
  const msg = {
    source: 'ailia-tts-bg',
    type: 'playAudio',
    audio: data,
    format: format || 'wav_24000',
    turnId,
    seq,
  };
  let exists = false;
  try { exists = await chrome.offscreen.hasDocument(); } catch (_) {}
  if (!exists || !offscreenReady) {
    log('offscreen not available, queueing audio chunk:', turnId, 'seq:', seq);
    audioQueue.push(msg);
    await ensureOffscreen();
    return;
  }
  try {
    await chrome.runtime.sendMessage(msg);
  } catch (e) {
    warn('sendMessage to offscreen failed, re-queueing:', e.message);
    offscreenReady = false;
    audioQueue.push(msg);
    await ensureOffscreen();
  }
}

function flushAudioQueue() {
  if (!audioQueue.length) return;
  log(`flushing ${audioQueue.length} queued audio message(s)`);
  const toSend = audioQueue.splice(0);
  (async () => {
    for (const msg of toSend) {
      try {
        await chrome.runtime.sendMessage(msg);
      } catch (e) {
        warn('flush sendMessage failed, re-queueing:', e.message);
        audioQueue.push(msg);
        offscreenReady = false;
        break;
      }
    }
  })();
}

async function ensureOffscreen() {
  let exists = false;
  try { exists = await chrome.offscreen.hasDocument(); } catch (_) {}
  if (exists) return;
  log('creating offscreen audio document');
  offscreenReady = false;
  await chrome.offscreen.createDocument({
    url: 'src/offscreen.html',
    reasons: ['AUDIO_PLAYBACK'],
    justification: 'Play TTS audio responses',
  });
}

// --- Message handling from content script --------------------------------

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.source === 'ailia-tts-offscreen' && msg.type === 'offscreenReady') {
    log('offscreen ready signal received');
    offscreenReady = true;
    flushAudioQueue();
    return;
  }

  if (msg.source !== 'ailia-tts-content') return;

  (async () => {
    await loadSettings();
    if (!settings.enabled) {
      log('TTS disabled, ignoring');
      return;
    }
    connect();

    // Forward streaming protocol messages directly to TTS server
    if (msg.type === 'turn_start') {
      turnSeqs.set(msg.turnId, 0);
      sendToServer({ type: 'turn_start', turnId: msg.turnId, voice: settings.voice });
    } else if (msg.type === 'text_delta') {
      sendToServer({ type: 'text_delta', turnId: msg.turnId, text: msg.text });
    } else if (msg.type === 'turn_end') {
      sendToServer({ type: 'turn_end', turnId: msg.turnId });
    } else if (msg.type === 'cancel') {
      sendToServer({ type: 'cancel', turnId: msg.turnId });
      turnSeqs.delete(msg.turnId);
      // Stop playback
      await ensureOffscreen();
      chrome.runtime.sendMessage({
        source: 'ailia-tts-bg',
        type: 'stopAudio',
        turnId: msg.turnId,
      });
    }
  })();
  return false;
});

chrome.storage.onChanged.addListener(() => {
  log('settings changed, reconnecting');
  if (ws) { try { ws.close(); } catch (_) {} ws = null; }
  wsReady = false;
  loadSettings().then(() => connect());
});

// Initialize
loadSettings().then(() => connect());
log(`background worker v${VERSION} loaded (localhost streaming mode)`);
