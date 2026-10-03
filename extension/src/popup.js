// Ailia TTS — popup settings logic (v0.2.0 localhost mode)
const $ = (id) => document.getElementById(id);
const DEFAULT_URL = 'ws://127.0.0.1:18766';

async function load() {
  const s = await chrome.storage.sync.get({
    ttsServerUrl: DEFAULT_URL,
    voice: 'ailia',
    enabled: true,
  });
  $('ttsServerUrl').value = s.ttsServerUrl;
  $('voice').value = s.voice;
  $('enabled').checked = s.enabled;
  updateStatus(s);
}

function updateStatus(s) {
  const el = $('status');
  if (!s.enabled) {
    el.textContent = 'TTS가 꺼져 있습니다.';
    el.className = 'status';
  } else if (s.ttsServerUrl) {
    el.textContent = '✅ 로컬 서버 모드: ' + s.ttsServerUrl;
    el.className = 'status ok';
  } else {
    el.textContent = '⚠️ 서버 URL을 입력하세요.';
    el.className = 'status';
  }
}

$('save').addEventListener('click', async () => {
  const s = {
    ttsServerUrl: $('ttsServerUrl').value.trim().replace(/\/$/, '') || DEFAULT_URL,
    voice: $('voice').value,
    enabled: $('enabled').checked,
  };
  await chrome.storage.sync.set(s);
  updateStatus(s);
  const prev = $('status').textContent;
  $('status').textContent = '💾 저장됨. ' + prev;
});

$('test').addEventListener('click', async () => {
  const url = $('ttsServerUrl').value.trim() || DEFAULT_URL;
  const el = $('status');
  el.textContent = '🔄 연결 테스트 중...';
  el.className = 'status';
  try {
    const ws = new WebSocket(url);
    const timeout = setTimeout(() => {
      try { ws.close(); } catch (_) {}
      el.textContent = '❌ 연결 실패 (시간 초과). 서버가 실행 중인지 확인하세요.';
      el.className = 'status err';
    }, 5000);
    ws.onopen = () => {
      clearTimeout(timeout);
      el.textContent = '✅ 서버 연결 성공!';
      el.className = 'status ok';
      ws.close();
    };
    ws.onerror = () => {
      clearTimeout(timeout);
      el.textContent = '❌ 연결 실패. 서버가 실행 중인지 확인하세요.';
      el.className = 'status err';
    };
  } catch (e) {
    el.textContent = '❌ 오류: ' + e.message;
    el.className = 'status err';
  }
});

$('enabled').addEventListener('change', async () => {
  const s = await chrome.storage.sync.get({ ttsServerUrl: DEFAULT_URL, voice: 'ailia', enabled: true });
  s.enabled = $('enabled').checked;
  updateStatus(s);
});
load();
