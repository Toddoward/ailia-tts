// Ailia TTS — background service worker (MV3) v0.2.4
// Thin router: content script -> offscreen document.
// The WebSocket lives in the offscreen document (not here) because MV3
// service workers are terminated aggressively, dropping in-memory queues.

const VERSION = '0.2.4';
const DEFAULT_WS_URL = 'ws://127.0.0.1:18766';

let settings = null;
let offscreenReady = false;
let creatingOffscreen = null;
const pendingToOffscreen = [];

function log(...args) { console.log('[ailia-tts][bg]', ...args); }
function warn(...args) { console.warn('[ailia-tts][bg]', ...args); }

async function loadSettings() {
  const s = await chrome.storage.sync.get({
    ttsServerUrl: DEFAULT_WS_URL,
    voice: 'F1',
    enabled: true,
  });
  settings = s;
  return s;
}

async function ensureOffscreen() {
  let exists = false;
  try { exists = await chrome.offscreen.hasDocument(); } catch (_) {}
  if (exists) return;
  if (creatingOffscreen) {
    // Another call is already creating it; wait for it.
    await creatingOffscreen;
    return;
  }
  log('creating offscreen document');
  offscreenReady = false;
  creatingOffscreen = (async () => {
    try {
      await chrome.offscreen.createDocument({
        url: 'src/offscreen.html',
        reasons: ['AUDIO_PLAYBACK'],
        justification: 'Play TTS audio and hold the streaming WebSocket',
      });
    } catch (e) {
      // "Only a single offscreen document may be created" — someone beat us.
      warn('offscreen create:', e.message);
    } finally {
      creatingOffscreen = null;
    }
  })();
  await creatingOffscreen;
}

function pushConfigToOffscreen() {
  if (!offscreenReady || !settings) return;
  chrome.runtime.sendMessage({
    source: 'ailia-tts-bg-config',
    ttsServerUrl: settings.ttsServerUrl,
    voice: settings.voice,
  }).catch(() => {});
}

async function routeToOffscreen(msg) {
  await ensureOffscreen();
  const out = { source: 'ailia-tts-bg', ...msg };
  delete out.source; // keep original below
  out.source = 'ailia-tts-bg';
  if (!offscreenReady) {
    pendingToOffscreen.push(out);
    return;
  }
  try {
    await chrome.runtime.sendMessage(out);
  } catch (e) {
    warn('route to offscreen failed, queueing:', e.message);
    offscreenReady = false;
    pendingToOffscreen.push(out);
    await ensureOffscreen();
  }
}

function flushPending() {
  if (!pendingToOffscreen.length) return;
  const toSend = pendingToOffscreen.splice(0);
  (async () => {
    for (const msg of toSend) {
      try {
        await chrome.runtime.sendMessage(msg);
      } catch (e) {
        warn('flush failed, re-queueing');
        pendingToOffscreen.unshift(msg);
        offscreenReady = false;
        break;
      }
    }
  })();
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.source === 'ailia-tts-offscreen' && msg.type === 'offscreenReady') {
    log('offscreen ready');
    offscreenReady = true;
    pushConfigToOffscreen();
    flushPending();
    return;
  }

  if (msg.source !== 'ailia-tts-content') return;

  (async () => {
    await loadSettings();
    if (!settings.enabled) return;
    pushConfigToOffscreen();
    await routeToOffscreen(msg);
  })();
  return false;
});

chrome.storage.onChanged.addListener(() => {
  loadSettings().then(() => pushConfigToOffscreen());
});

// Warm up the offscreen document at startup so the WebSocket is ready.
loadSettings().then(() => ensureOffscreen().then(pushConfigToOffscreen));
log(`background worker v${VERSION} loaded (router mode)`);
