/* 刷词 · 前端
   流程：看词 → 点「认识 / 不认识」→ 翻面看中文 → 记错了或不会的进收藏 */

const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const esc = s => String(s == null ? '' : s)
  .replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const S = { words: [], byWord: {}, sources: [], missing: [], stats: {}, today: '',
            sourceIssues: [], orphanCount: 0 };
const Q = { list: [], i: 0, flipped: null, favShown: false, mode: 'mix', done: new Set() };

const DEFAULT_CFG = { mode: 'mix', shuffle: false, requeue: true, dailyNew: 150, hints: false,
                      favScope: 'all', favNewest: true };
let CFG = Object.assign({}, DEFAULT_CFG, load('shuaci.cfg', {}));

function load(k, d) {
  try { return JSON.parse(localStorage.getItem(k)) || d; } catch (e) { return d; }
}
function save(k, v) { localStorage.setItem(k, JSON.stringify(v)); }

async function api(path, body) {
  const opt = body
    ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
    : {};
  const r = await fetch(path, opt);
  return r.json();
}

function toast(msg, kind) {
  const t = $('#toast');
  t.textContent = msg;
  t.className = 'toast' + (kind ? ' ' + kind : '');
  t.hidden = false;
  clearTimeout(t._t);
  t._t = setTimeout(() => { t.hidden = true; }, 1600);
}

/* ---------- 发音 ---------- */

const SPK = `<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
  <path d="M4 9.5v5h3.6L13 19.5v-15L7.6 9.5H4z" fill="currentColor"/>
  <path d="M16.2 9a4.2 4.2 0 0 1 0 6" fill="none" stroke="currentColor"
        stroke-width="1.8" stroke-linecap="round"/></svg>`;

let AUDIO = null;
function say(w) {
  if (!w) return;
  try {
    if (AUDIO) AUDIO.pause();
    // 有道发音接口，不用 key。type=2 美音，type=1 英音
    AUDIO = new Audio('https://dict.youdao.com/dictvoice?audio=' +
                      encodeURIComponent(w) + '&type=2');
    AUDIO.play().catch(() => toast('发音加载失败，检查一下联网'));
  } catch (e) {
    toast('发音失败');
  }
}

/* ---------- 载入 ---------- */

async function loadState(reload) {
  const d = await api('/api/state' + (reload ? '?reload=1' : ''));
  S.words = d.words;
  S.byWord = {};
  d.words.forEach(w => { S.byWord[w.w] = w; });
  S.sources = d.sources;
  S.missing = d.missing;
  S.stats = d.stats;
  S.today = d.stats.today;
  S.defaultTarget = d.defaultTarget;
  S.sourceIssues = d.sourceIssues || [];
  S.orphanCount = d.orphanCount || 0;
  updateTop();
  renderWarn();
  buildQueue();
  renderCard();
}

/* 词表文件被移走/删掉时，明确说出来。
   不然界面只是静静地显示「共 0」，看着像数据全没了 */
function renderWarn() {
  const bar = $('#warnBar');
  const bad = S.sourceIssues || [];
  if (!bad.length) {
    bar.classList.remove('on');
    bar.innerHTML = '';
    return;
  }
  bar.classList.add('on');
  bar.innerHTML =
    `<span><b>词表文件找不到了</b>：${bad.map(b => `<code>${b.path}</code>`).join('、')}</span>
     <span class="sub">学习记录没丢，${S.orphanCount} 个学过的词和收藏都还在。把文件放回原处，或去「词表来源」重新指定一个。</span>
     <button class="mini" id="warnGo">去处理</button>`;
  $('#warnGo').onclick = () => switchView('src');
}

function updateTop() {
  const doneToday = S.stats.doneToday || 0;
  $('#topInfo').textContent =
    `共 ${S.stats.total} · 新词 ${S.stats.new} · 收藏 ${S.stats.fav} · 今日已过 ${doneToday}`;
  $('#badgeFav').textContent = S.stats.fav;
}

/* ---------- 队列 ---------- */

function isNew(w) { return !w.st; }
function isFav(w) { return w.st && w.st.fav && !w.st.mastered; }
function isDue(w) { return !w.st.due || w.st.due <= S.today; }

function shuffle(a) {
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

function buildQueue() {
  const   favs = S.words.filter(w => isFav(w) && isDue(w))
    .sort((a, b) => String(a.st.due).localeCompare(String(b.st.due)));
  const news = S.words.filter(isNew);
  // 今天已经过掉的词要算进额度，重开页面才不会又塞 150 个新的进来
  const cap = Math.max(10, (CFG.dailyNew | 0) - (S.stats.doneToday || 0));

  let list = [];
  if (Q.mode === 'new') list = news.slice(0, cap);
  else if (Q.mode === 'fav') list = favs.slice();
  else list = favs.concat(news.slice(0, cap));

  if (CFG.shuffle) shuffle(list);
  Q.list = list;
  Q.planned = list.length;   // 本轮计划量，固定不变，答错回炉的不算进来
  Q.i = 0;
  Q.flipped = null;
  Q.done = new Set();
}

/* ---------- 刷词主界面 ---------- */

function cur() { return Q.list[Q.i]; }

function renderCard() {
  const w = cur();
  const card = $('#card');
  // 分母用本轮计划量（固定），答错回炉的词单独计成"待巩固"，不然总数会一直涨
  const planned = Q.planned || Q.list.length;
  const extra = Math.max(0, Q.list.length - planned);
  const passed = Math.min(Q.i, planned);
  $('#drillCount').textContent = Q.list.length
    ? `${passed} / ${planned}` + (extra ? `　＋${extra} 待巩固` : '')
    : '';
  const pct = planned ? Math.min(100, (passed / planned) * 100) : 0;
  $('#pbarFill').style.width = pct + '%';

  if (!w) {
    $('#ph').textContent = '';
    $('#word').textContent = '这一轮刷完了';
    $('#mean').hidden = true;
    $('#tip').hidden = true;
    $('#ctx').hidden = true;
    $('#btnSay').hidden = true;
    $('#acts').innerHTML =
      `<button class="btn" data-a="again">再来一轮</button>
       <button class="btn ghost" data-a="favdrill">去刷收藏</button>
       <button class="btn ghost" data-a="all">看词表</button>`;
    return;
  }

  $('#word').textContent = w.w;
  $('#btnSay').hidden = false;
  $('#btnSay').onclick = () => say(w.w);
  // 默认只给单词本身，音标和搭配提示都算提示，想看再开开关
  $('#ph').textContent = CFG.hints && w.ph ? '/' + w.ph + '/' : '';

  if (Q.flipped) {
    const m = $('#mean');
    m.hidden = false;
    m.textContent = w.m || '（这个词还没有释义，按 E 补一个，或去「词表来源」联网补全）';
    m.className = 'mean' + (w.m ? '' : ' empty');
    if (CFG.hints && w.tip) { $('#tip').textContent = w.tip; $('#tip').hidden = false; }
    else $('#tip').hidden = true;
    // 派生词也是答案的一部分，跟原句一样翻面后才给
    const rel = w.rel || [];
    if (rel.length) {
      $('#rel').textContent = '派生　'
        + rel.map(r => `${r.w} ${r.pos} ${r.m}`).join('　·　');
      $('#rel').hidden = false;
    } else $('#rel').hidden = true;
    // 读到它的那句话，属于答案的一部分，翻面后才给看
    if (w.ctx) { $('#ctx').textContent = w.ctx; $('#ctx').hidden = false; }
    else $('#ctx').hidden = true;
  } else {
    $('#mean').hidden = true;
    $('#tip').hidden = true;
    // 派生词也得清掉，不然上一张翻面带出来的会一直挂在新词下面
    $('#rel').hidden = true;
    $('#ctx').hidden = true;
  }

  const fav = isFav(w);
  let html = '';
  if (!Q.flipped) {
    html = `<button class="btn ok" data-a="know">认识 <span class="kb">1</span></button>
            <button class="btn no" data-a="unknow">不认识 <span class="kb">2</span></button>`;
  } else if (Q.flipped === 'know') {
    html = `<button class="btn ok" data-a="next">记住了，下一个</button>
            <button class="btn star" data-a="wrong">其实记错了 ★</button>
            <button class="btn ghost small" data-a="fav">${fav ? '取消收藏' : '收藏'}</button>
            <button class="btn ghost small" data-a="edit">改释义</button>`;
  } else {
    html = `<button class="btn" data-a="next">下一个</button>
            <button class="btn star" data-a="unfav">已收藏 ★（点一下取消）</button>
            <button class="btn ghost small" data-a="edit">改释义</button>`;
  }
  $('#acts').innerHTML = html;
}

async function act(a) {
  const w = cur();
  if (!w) {
    if (a === 'again') { buildQueue(); renderCard(); }
    if (a === 'favdrill') { setMode('fav'); switchView('drill'); }
    if (a === 'all') switchView('all');
    return;
  }
  if (a === 'know') { Q.flipped = 'know'; renderCard(); return; }
  if (a === 'unknow') {
    Q.flipped = 'unknown';
    await mark(w, { right: false, fav: true });
    renderCard();
    return;
  }
  if (a === 'wrong') { await mark(w, { right: false, fav: true }); next(); return; }
  if (a === 'next') { if (Q.flipped === 'know') await mark(w, { right: true }); next(); return; }
  if (a === 'fav') { await toggleFav(w); renderCard(); return; }
  if (a === 'unfav') { await toggleFav(w); renderCard(); return; }
  if (a === 'edit') { openModal(w); return; }
}

async function mark(w, { right, fav }) {
  const st = await api('/api/mark', { word: w.w, right, fav, requeue: CFG.requeue });
  w.st = st;
  S.stats.doneToday = (S.stats.doneToday || 0) + 1;
  if (!right && CFG.requeue && !w._re) { w._re = true; Q.list.push(w); }
  S.stats.fav = S.words.filter(isFav).length;
  S.stats.new = S.words.filter(isNew).length;
  updateTop();
}

async function toggleFav(w) {
  const st = await api('/api/fav', { word: w.w, fav: !isFav(w) });
  w.st = st;
  S.stats.fav = S.words.filter(isFav).length;
  updateTop();
  toast(st.fav ? '已收藏 ★' : '已取消收藏');
}

function next() {
  const w = cur();
  if (w) Q.done.add(w.w);
  Q.i++;
  Q.flipped = null;
  renderCard();
}

/* ---------- 收藏本 ---------- */

const pad2 = n => String(n).padStart(2, '0');

/* 收藏时刻。老记录只有日期，ord 是写入顺序，用来撑同一天里的先后 */
function favStamp(w) {
  return [(w.st && w.st.favAt) || '0', (w.st && w.st.ord) || 0];
}

function favWhen(w) {
  const s = (w.st && w.st.favAt) || '';
  const t = Date.parse(s.replace(' ', 'T'));
  if (!t) return '';
  const d = new Date(t);
  const ds = `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
  if (ds === S.today) return '今天';
  const y = new Date(Date.parse(S.today + 'T00:00:00') - 86400000);
  const yds = `${y.getFullYear()}-${pad2(y.getMonth() + 1)}-${pad2(y.getDate())}`;
  if (ds === yds) return '昨天';
  return ds.slice(5);
}

function renderFav() {
  const kw = $('#favSearch').value.trim().toLowerCase();
  const scope = $('#favScope').value;
  let list = S.words.filter(isFav)
    .filter(w => !kw || w.w.includes(kw) || (w.m || '').includes(kw)
                     || (w.ctx || '').includes(kw));
  if (scope === 'today') {
    list = list.filter(w => ((w.st && w.st.favAt) || '').slice(0, 10) === S.today);
  }
  list.sort((a, b) => {
    const x = favStamp(a), y = favStamp(b);
    let c = x[0] === y[0] ? 0 : (x[0] < y[0] ? -1 : 1);
    if (!c) c = x[1] - y[1];
    return CFG.favNewest ? -c : c;
  });
  $('#favCount').textContent = scope === 'today' ? `今天 ${list.length} 个` : `共 ${list.length} 个`;
  $('#favList').innerHTML = list.map(w => {
    const when = favWhen(w);
    return `
    <div class="row" data-w="${w.w}">
      <span class="w">${w.w}</span>
      <button class="spk tiny" data-a="say" title="发音">${SPK}</button>
      <span class="m hide" data-a="show" title="点一下看意思，再点收起">${esc(w.m) || '（无释义）'}</span>
      <span class="tag">${when ? `${when}　` : ''}box ${(w.st && w.st.box) || 0} · 错 ${(w.st && w.st.wrong) || 0} 次</span>
      ${w.ctx ? `<span class="tag ctxq" title="${esc(w.ctx)}">原句</span>` : ''}
      <span class="ops">
        <button class="mini" data-a="master">已掌握</button>
        <button class="mini" data-a="delfav">移出</button>
        <button class="mini" data-a="edit">改</button>
      </span>
    </div>`;
  }).join('') || '<p class="hint">收藏是空的。刷词时点「不认识」或「记错了」就会进来。</p>';
}

/* ---------- 全部词表 ---------- */

function renderAll() {
  const kw = $('#allSearch').value.trim().toLowerCase();
  const f = $('#allFilter').value;
  const list = S.words.filter(w => {
    if (kw && !w.w.includes(kw) && !(w.m || '').includes(kw)
        && !(w.ctx || '').includes(kw)) return false;
    if (f === 'new') return isNew(w);
    if (f === 'fav') return isFav(w);
    if (f === 'done') return w.st && w.st.mastered;
    if (f === 'missing') return !w.m;
    return true;
  });
  $('#allCount').textContent = `${list.length} / ${S.words.length}`;
  $('#allList').innerHTML = list.map(w => {
    let tag = '';
    if (w.st && w.st.mastered) tag = '<span class="tag">√ 已掌握</span>';
    else if (isFav(w)) tag = '<span class="tag">★</span>';
    return `<div class="row ${w.st && w.st.mastered ? 'learned' : ''}" data-w="${w.w}">
      <span class="w">${w.w}</span>
      <button class="spk tiny" data-a="say" title="发音">${SPK}</button>
      <span class="m ${w.m ? '' : 'muted'}" data-a="edit">${esc(w.m) || '（无释义，点击补）'}</span>
      ${tag}
      ${w.ctx ? `<span class="tag ctxq" title="${esc(w.ctx)}">原句</span>` : ''}
      <span class="ops">
        <button class="mini" data-a="fav">${isFav(w) ? '取消收藏' : '收藏'}</button>
        <button class="mini" data-a="edit">改</button>
      </span>
    </div>`;
  }).join('') || '<p class="hint">没有匹配的词。</p>';
}

/* ---------- 来源 / 设置 ---------- */

function renderSrc() {
  $('#srcList').innerHTML = S.sources.map(s => `
    <div class="src-item ${s.exists === false ? 'bad' : ''}">
      <span class="name">${s.name}</span>
      <span class="path">${s.path}</span>
      ${s.exists === false ? '<span class="miss">文件不存在</span>' : `<span class="count">${s.count} 词</span>`}
      <button class="mini" data-a="reload">重新读取</button>
      <button class="mini" data-a="delsrc" data-p="${s.path}">移除</button>
    </div>`).join('') || '<p class="hint">还没有词表，拖一个 md 进来。</p>';
  if (!$('#addTarget').value) $('#addTarget').value = S.defaultTarget || '';
  if (!$('#addSection').value) $('#addSection').placeholder =
    S.today.replace(/-/g, '').slice(2) + '_词表';
  $('#missingInfo').textContent = S.missing.length
    ? `有 ${S.missing.length} 个词还没有中文意思。可以直接联网补全，也可以刷到它时按 E 手填。`
    : '所有词都有释义了。';
  $('#btnFill').disabled = !S.missing.length;
}

/* ---------- 改释义 ---------- */

let editing = null;
function openModal(w) {
  editing = w;
  $('#mWord').textContent = w.w;
  $('#mInput').value = w.m || '';
  $('#mInput2').value = w.tip || '';
  $('#mInput3').value = w.ctx || '';
  $('#modal').classList.add('on');
  $('#mInput').focus();
}
async function saveModal() {
  if (!editing) return;
  const m = $('#mInput').value.trim();
  const tip = $('#mInput2').value.trim();
  const ctx = $('#mInput3').value.trim();
  await api('/api/dict', { word: editing.w, meaning: m, tip, ctx });
  editing.m = m;
  editing.tip = tip;
  editing.ctx = ctx;
  $('#modal').classList.remove('on');
  toast('已保存', 'good');
  renderCard();
  if ($('#view-fav').classList.contains('on')) renderFav();
  if ($('#view-all').classList.contains('on')) renderAll();
}

/* ---------- 视图 / 事件 ---------- */

function switchView(v) {
  $$('.tab').forEach(t => t.classList.toggle('on', t.dataset.view === v));
  $$('.view').forEach(s => s.classList.toggle('on', s.id === 'view-' + v));
  if (v === 'fav') renderFav();
  if (v === 'all') renderAll();
  if (v === 'src') renderSrc();
  if (v === 'drill') renderCard();
}

function setMode(m) {
  Q.mode = m;
  CFG.mode = m;
  save('shuaci.cfg', CFG);
  $$('#modeSeg button').forEach(b => b.classList.toggle('on', b.dataset.mode === m));
  buildQueue();
  renderCard();
}

function bind() {
  $$('.tab').forEach(t => t.onclick = () => switchView(t.dataset.view));
  $$('#modeSeg button').forEach(b => b.onclick = () => setMode(b.dataset.mode));
  $('#acts').onclick = e => {
    const b = e.target.closest('[data-a]');
    if (b) act(b.dataset.a);
  };
  $('#btnRestart').onclick = () => { buildQueue(); renderCard(); toast('重新开始了'); };
  $('#favSearch').oninput = renderFav;
  $('#favScope').value = CFG.favScope || 'all';
  $('#favScope').onchange = e => {
    CFG.favScope = e.target.value; save('shuaci.cfg', CFG); renderFav();
  };
  $('#favSort').onclick = () => {
    CFG.favNewest = !CFG.favNewest;
    save('shuaci.cfg', CFG);
    $('#favSort').textContent = CFG.favNewest ? '最新在前' : '最早在前';
    renderFav();
  };
  $('#favSort').textContent = CFG.favNewest ? '最新在前' : '最早在前';
  $('#allSearch').oninput = renderAll;
  $('#allFilter').onchange = renderAll;
  $('#btnFavDrill').onclick = () => { setMode('fav'); switchView('drill'); };
  $('#favList').onclick = e => rowClick(e, true);
  $('#allList').onclick = e => rowClick(e, false);

  $('#optShuffle').checked = CFG.shuffle;
  $('#optRequeue').checked = CFG.requeue;
  $('#optDaily').value = CFG.dailyNew;
  $('#optHints').checked = !!CFG.hints;
  $('#optHints').onchange = e => { CFG.hints = e.target.checked; save('shuaci.cfg', CFG); renderCard(); };
  $('#optShuffle').onchange = e => { CFG.shuffle = e.target.checked; save('shuaci.cfg', CFG); buildQueue(); renderCard(); };
  $('#optRequeue').onchange = e => { CFG.requeue = e.target.checked; save('shuaci.cfg', CFG); };
  $('#optDaily').onchange = e => { CFG.dailyNew = e.target.value | 0; save('shuaci.cfg', CFG); buildQueue(); renderCard(); };

  $('#mSave').onclick = saveModal;
  $('#mCancel').onclick = () => { $('#modal').classList.remove('on'); };
  $('#mInput').onkeydown = e => { if (e.key === 'Enter') saveModal(); };

  $('#btnPick').onclick = () => $('#filePick').click();
  $('#filePick').onchange = e => { [...e.target.files].forEach(upload); e.target.value = ''; };
  const drop = $('#drop');
  drop.ondragover = e => { e.preventDefault(); drop.classList.add('over'); };
  drop.ondragleave = () => drop.classList.remove('over');
  drop.ondrop = e => {
    e.preventDefault();
    drop.classList.remove('over');
    [...e.dataTransfer.files].forEach(upload);
  };
  $('#srcList').onclick = e => {
    const b = e.target.closest('[data-a]');
    if (!b) return;
    if (b.dataset.a === 'reload') loadState(true).then(() => { renderSrc(); toast('已重新读取'); });
    if (b.dataset.a === 'delsrc') api('/api/source/remove', { path: b.dataset.p }).then(loadState).then(renderSrc);
  };

  $('#btnAdd').onclick = async () => {
    const text = $('#addText').value.trim();
    if (!text) { toast('先粘点词进来'); return; }
    $('#addInfo').textContent = '正在加入…';
    const r = await api('/api/append', {
      text,
      target: $('#addTarget').value.trim() || S.defaultTarget,
      section: $('#addSection').value.trim(),
    });
    $('#addText').value = '';
    if ($('#addFill').checked && r.added && r.added.length) {
      $('#addInfo').textContent = `已加 ${r.count} 词，正在补全释义…`;
      const f = await api('/api/fill', { words: r.added });
      $('#addInfo').textContent = `已加 ${r.count} 词，补全 ${f.ok} 条释义${f.fail ? `，失败 ${f.fail}` : ''}`;
    } else {
      $('#addInfo').textContent = `已加 ${r.count} 词`;
    }
    await loadState(true);
    renderSrc();
    toast(`加了 ${r.count} 个词`, 'good');
  };

  $('#btnFill').onclick = async () => {
    $('#btnFill').disabled = true;
    $('#fillInfo').textContent = '正在联网补全…';
    const r = await api('/api/fill', { words: S.missing.slice(0, 400) });
    await loadState(true);
    renderSrc();
    $('#fillInfo').textContent = `成功 ${r.ok} 个，失败 ${r.fail} 个`;
    toast(`补全了 ${r.ok} 个`, 'good');
  };

  $('#btnFillRel').onclick = async () => {
    const b = $('#btnFillRel');
    b.disabled = true;
    $('#fillRelInfo').textContent = '正在补派生词…（一次 40 个，没补完再点一次）';
    const r = await api('/api/fillrel', {});
    await loadState(true);
    renderSrc();
    $('#fillRelInfo').textContent =
      `补了 ${r.ok} 个${r.fail ? `，${r.fail} 个没派生词` : ''}`
      + (r.remain ? `，还剩 ${r.remain} 个，再点一次` : '，全部补完了');
    b.disabled = false;
    toast(`补了 ${r.ok} 个派生词`, 'good');
  };

  $('#btnRefill').onclick = async () => {
    const b = $('#btnRefill');
    b.disabled = true;
    $('#refillInfo').textContent = '正在重刷…（一次 40 个，没刷完就再点一次）';
    const r = await api('/api/refill', {});
    await loadState(true);
    renderSrc();
    $('#refillInfo').textContent =
      `成功 ${r.ok} 个${r.fail ? `，失败 ${r.fail}` : ''}`
      + (r.remain ? `，还剩 ${r.remain} 个，再点一次` : '，全部刷完了');
    b.disabled = false;
    toast(`重刷了 ${r.ok} 个`, 'good');
  };

  $('#btnExport').onclick = async () => {
    const md = await (await fetch('/api/export?fmt=md')).text();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([md], { type: 'text/markdown;charset=utf-8' }));
    a.download = `生词整理_${S.today}.md`;
    a.click();
  };

  $('#btnResetFav').onclick = async () => {
    if (!confirm('清空所有收藏状态？学习记录保留。')) return;
    await api('/api/reset', { scope: 'fav' });
    await loadState(true);
    toast('收藏已清空');
  };
  $('#btnResetAll').onclick = async () => {
    if (!confirm('清空全部学习记录？词表和释义不受影响。')) return;
    await api('/api/reset', { scope: 'all' });
    await loadState(true);
    toast('学习记录已清空');
  };

  document.onkeydown = e => {
    if ($('#modal').classList.contains('on')) return;
    if (document.activeElement.tagName === 'INPUT' && document.activeElement.type !== 'checkbox') return;
    const v = $$('.view.on')[0].id;
    if (v === 'view-drill') {
      if (e.key === '1') act('know');
      else if (e.key === '2') act('unknow');
      else if (e.key === ' ' || e.key === 'Enter') {
        e.preventDefault();
        Q.flipped ? act('next') : act('know');
      } else if (e.key === 'p' || e.key === 'P') { const c = cur(); if (c) say(c.w); }
      else if (e.key === 's' || e.key === 'S') { act(Q.flipped === 'unknown' ? 'unfav' : 'fav'); }
      else if (e.key === 'e' || e.key === 'E') { act('edit'); }
      else if (e.key === 'r' || e.key === 'R') { buildQueue(); renderCard(); }
    }
    if (e.key === 'Escape') $('#modal').classList.remove('on');
  };
}

async function rowClick(e, isFavView) {
  const el = e.target.closest('[data-a]');
  if (!el) return;
  const w = S.byWord[el.closest('.row').dataset.w];
  const a = el.dataset.a;
  if (a === 'show') { el.classList.toggle('hide'); return; }
  if (a === 'say') { say(w.w); return; }
  if (a === 'edit') { openModal(w); return; }
  if (a === 'fav') { await toggleFav(w); renderAll(); return; }
  if (a === 'delfav') { await api('/api/fav', { word: w.w, fav: false }); await loadState(); renderFav(); return; }
  if (a === 'master') {
    await api('/api/fav', { word: w.w, fav: false, mastered: true });
    await loadState();
    renderFav();
    toast('已标记为掌握');
  }
}

async function upload(f) {
  const text = await f.text();
  await api('/api/source/add', { name: f.name, content: text });
  await loadState(true);
  if ($('#view-src').classList.contains('on')) renderSrc();
  toast(`已加入 ${f.name}`, 'good');
}

(async function init() {
  bind();
  setMode(CFG.mode);
  await loadState();
})();
