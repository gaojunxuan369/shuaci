/* 刷词 · 划词收录
   划中一个英文单词 -> 右键 -> 收进本地词库，顺便带上读到它的那句话。
   只跟 127.0.0.1 上的 server.py 说话，不经过任何外部服务器。 */

const PORT_FROM = 8756;
const PORT_TO = 8776;      // server.py 从 8756 起找空位，最多试 20 个

/* ---------- 找服务 ---------- */

async function ping(base) {
  try {
    const r = await fetch(base + '/api/state', { cache: 'no-store' });
    if (!r.ok) return null;
    return await r.json();
  } catch (e) {
    return null;
  }
}

// 端口是服务启动时挑的，每次可能不一样，所以每次都确认一遍
async function findService() {
  const { base } = await chrome.storage.local.get('base');
  if (base) {
    const s = await ping(base);
    if (s) return { base, state: s };
  }
  for (let p = PORT_FROM; p < PORT_TO; p++) {
    const b = 'http://127.0.0.1:' + p;
    const s = await ping(b);
    if (s) {
      await chrome.storage.local.set({ base: b });
      return { base: b, state: s };
    }
  }
  return null;
}

/* ---------- 收词 ---------- */

function cleanWord(s) {
  return (s || '').trim().replace(/^[^a-zA-Z]+/, '').replace(/[^a-zA-Z]+$/, '').toLowerCase();
}

function isWord(w) {
  return /^[a-zA-Z][a-zA-Z'\-]*$/.test(w);
}

function notify(msg) {
  chrome.notifications.create({
    type: 'basic',
    iconUrl: 'icon48.png',
    title: '刷词',
    message: String(msg).slice(0, 200),
  });
}

// 这段会被注入到页面里跑，不能引用外面的变量
function getContext(word) {
  try {
    const sel = window.getSelection();
    let el = sel && sel.anchorNode;
    if (el && el.nodeType === 3) el = el.parentElement;
    // 往上找到一个够长的容器，句子才完整
    while (el && el.parentElement && el.textContent.trim().length < 300) {
      el = el.parentElement;
    }
    const full = (el ? el.textContent : '').replace(/\s+/g, ' ').trim();
    if (!full) return '';
    const lw = String(word).toLowerCase();
    // 按句号切，取包含这个词的那一句
    let parts = [];
    try {
      parts = full.split(/(?<=[.!?;。！？；])\s+/);
    } catch (e) {
      parts = full.split(/[.!?。！？；]/);
    }
    let s = parts.find(p => p.toLowerCase().includes(lw)) || full;
    if (s.length > 300) {
      const i = s.toLowerCase().indexOf(lw);
      s = i > 0 ? s.slice(Math.max(0, i - 120), i + 180) : s.slice(0, 300);
    }
    return s.trim();
  } catch (e) {
    return '';
  }
}

async function addWord(word, tab) {
  const raw = cleanWord(word);
  if (!isWord(raw)) {
    notify('只收单个英文单词：' + String(word).slice(0, 30));
    return;
  }

  let ctx = '';
  try {
    const [r] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: getContext,
      args: [raw],
    });
    ctx = (r && r.result) || '';
  } catch (e) {
    ctx = '';                 // 拿不到句子也要能把词收进去
  }

  const found = await findService();
  if (!found) {
    notify('连不上刷词服务。先双击「启动.bat」，再回来划词。');
    return;
  }

  const cfg = await chrome.storage.local.get(['target', 'section']);
  const d = new Date();
  const ymd = '' + d.getFullYear() +
    String(d.getMonth() + 1).padStart(2, '0') + String(d.getDate()).padStart(2, '0');

  const body = {
    target: cfg.target || found.state.defaultTarget,
    section: cfg.section || ('划词_' + ymd),
    text: raw,
    ctxs: ctx ? { [raw]: ctx } : {},
    fill: true,               // 顺手让服务端联网补释义
  };

  try {
    const r = await fetch(found.base + '/api/append', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(x => x.json());
    if (!r || !r.count) {
      notify('没加进去，服务端返回：' + JSON.stringify(r).slice(0, 80));
      return;
    }
    notify(raw + ' 已加入' + (r.filled ? `，补了 ${r.filled} 条释义` : '') +
           (ctx ? '，带原句' : ''));
  } catch (e) {
    notify('发送失败：' + e.message);
  }
}

/* ---------- 注册 ---------- */

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: 'shuaci-add',
    title: '加入刷词词库',
    contexts: ['selection'],
  });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId !== 'shuaci-add') return;
  addWord(info.selectionText, tab);
});
