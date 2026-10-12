const PORT_FROM = 8756;
const PORT_TO = 8776;

const $ = s => document.querySelector(s);

async function ping(base) {
  try {
    const r = await fetch(base + '/api/state', { cache: 'no-store' });
    return r.ok ? await r.json() : null;
  } catch (e) {
    return null;
  }
}

function setSt(msg, kind) {
  const el = $('#st');
  el.textContent = msg;
  el.className = 'st' + (kind ? ' ' + kind : '');
}

async function check(base) {
  const s = await ping(base);
  if (!s) {
    setSt('连不上。确认刷词服务已启动（双击 启动.bat）。', 'bad');
    return null;
  }
  setSt(`已连上：共 ${s.stats.total} 词，其中新词 ${s.stats.new}、收藏 ${s.stats.fav}`, 'ok');
  return s;
}

async function scan() {
  setSt('正在探测端口…');
  for (let p = PORT_FROM; p < PORT_TO; p++) {
    const b = 'http://127.0.0.1:' + p;
    const s = await ping(b);
    if (s) {
      $('#base').value = b;
      await chrome.storage.local.set({ base: b });
      setSt(`找到了：${b}（共 ${s.stats.total} 词）`, 'ok');
      if (!$('#target').value && s.defaultTarget) $('#target').placeholder = s.defaultTarget;
      return;
    }
  }
  setSt('8756~8775 都没找到服务。先启动刷词再点这个。', 'bad');
}

(async function init() {
  const cfg = await chrome.storage.local.get(['base', 'target', 'section']);
  $('#base').value = cfg.base || ('http://127.0.0.1:' + PORT_FROM);
  $('#target').value = cfg.target || '';
  $('#section').value = cfg.section || '';
  const s = await check($('#base').value);
  if (s && !cfg.target && s.defaultTarget) $('#target').placeholder = s.defaultTarget;
})();

$('#scan').onclick = scan;

$('#save').onclick = async () => {
  await chrome.storage.local.set({
    base: $('#base').value.trim(),
    target: $('#target').value.trim(),
    section: $('#section').value.trim(),
  });
  await check($('#base').value.trim());
};

$('#open').onclick = async () => {
  const base = $('#base').value.trim();
  chrome.tabs.create({ url: base + '/' });
};
