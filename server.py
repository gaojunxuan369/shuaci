# -*- coding: utf-8 -*-
"""
刷词 · 本地服务
- 解析生词.md（纯单词行 / markdown 表格行 / 分组标题）
- dict.json    释义库（优先用 md 表格里自带的，其次本地库，最后联网抓）
- progress.json 学习记录（认识/不认识/收藏/间隔复习）
- sources.json  词表来源
双击 启动.bat 即可，只有一个 Python 标准库依赖。
"""

import glob
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
WEB = os.path.join(BASE, "web")
UPLOADS = os.path.join(DATA, "uploads")
DICT_F = os.path.join(DATA, "dict.json")
PROG_F = os.path.join(DATA, "progress.json")
SRC_F = os.path.join(DATA, "sources.json")

DEFAULT_MD = os.path.join(os.path.expanduser("~"), "Desktop", "生词.md")

WORD_RE = re.compile(r"^[a-zA-Z][a-zA-Z'\-]*$")
INTERVALS = [1, 1, 2, 4, 7, 15]  # box 0..5 之后的天数
MAX_BOX = 5


# ---------- 基础工具 ----------

def today():
    return date.today().isoformat()


def now_ts():
    """收藏时间，精确到秒，字符串比较就是时间顺序"""
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def norm(w):
    return w.strip().strip("*").strip().lower()


# ---------- 备份 ----------

BACKUP = os.path.join(DATA, "backup")


def backup_progress(tag="auto"):
    """学习记录是唯一不可再生的东西，每天留一份备份，保留最近 10 份。
    记录变少（比如被清空）时不覆盖当天已有的备份。"""
    try:
        if not os.path.exists(PROG_F):
            return None
        os.makedirs(BACKUP, exist_ok=True)
        dst = os.path.join(BACKUP, "progress_%s_%s.json" % (time.strftime("%Y%m%d"), tag))
        with open(PROG_F, "r", encoding="utf-8") as f:
            cur = f.read()
        if os.path.exists(dst):
            with open(dst, "r", encoding="utf-8") as f:
                old = f.read()
            if len(old) > len(cur):
                return dst
        with open(dst, "w", encoding="utf-8") as f:
            f.write(cur)
        files = sorted(glob.glob(os.path.join(BACKUP, "progress_*.json")))
        for old_f in files[:-10]:
            os.remove(old_f)
        return dst
    except Exception as e:
        print("[warn] 备份失败: %s" % e)
        return None


# ---------- 解析词表 ----------

def parse_md(text, src_name):
    """返回 [{w, meaning, tip, section, src}]"""
    out = []
    section = "未分组"
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):                       # # 标题
            section = line.lstrip("#").strip()[:40] or "未分组"
            continue
        if line.startswith("|"):                       # | word | 意思 | 提示 | 状态 | 原句 |
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) < 2 or set(cells[0]) <= set("-: "):
                continue
            w = norm(cells[0])
            if not WORD_RE.match(w):
                continue                               # 表头「单词」之类
            out.append({
                "w": w,
                "meaning": cells[1] if len(cells) > 1 else "",
                "tip": cells[2] if len(cells) > 2 else "",
                # 第 4 列是状态（★/√），第 5 列才是原句
                "ctx": cells[4] if len(cells) > 4 else "",
                "section": section,
                "src": src_name,
            })
            continue
        if WORD_RE.match(line):                        # 纯单词行
            out.append({"w": line.lower(), "meaning": "", "tip": "", "ctx": "",
                        "section": section, "src": src_name})
            continue
        if " - " in line:                              # word - 意思
            a, b = line.split(" - ", 1)
            if WORD_RE.match(a.strip()):
                out.append({"w": a.strip().lower(), "meaning": b.strip(), "tip": "", "ctx": "",
                            "section": section, "src": src_name})
                continue
        section = line[:40]                            # 其余当分组标题（261008_词表1-10页 这种）
    return out


_cache = {}


def read_source(path, name):
    try:
        st = os.stat(path)
        hit = _cache.get(path)
        if hit and hit[0] == st.st_mtime:
            return hit[1]
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            words = parse_md(f.read(), name)
        _cache[path] = (st.st_mtime, words)
        return words
    except Exception as e:
        print("[warn] 读取词表失败 %s: %s" % (path, e))
        return []


def search_dirs():
    """词表文件被挪走时，到这些地方按文件名找回来"""
    home = os.path.expanduser("~")
    desktop = os.path.dirname(DEFAULT_MD)
    return [BASE, desktop, UPLOADS, DATA,
            os.path.join(desktop, "生词"),
            os.path.join(home, "Documents"),
            os.path.join(home, "Downloads")]


def resolve_source(path, name):
    """返回真实可用的路径；原位置没了就按文件名在常见目录里找"""
    if path and os.path.exists(path):
        return path, False
    base = os.path.basename(path or name or "")
    if base:
        for d in search_dirs():
            cand = os.path.join(d, base)
            if os.path.exists(cand):
                return cand, True
        # 名字也改了的情况：同目录下只认文件名含「生词」的 md
        stem = os.path.splitext(base)[0] if base else ""
        for d in [os.path.dirname(path) if path else "", BASE, os.path.dirname(DEFAULT_MD)]:
            if not d or not os.path.isdir(d):
                continue
            cands = [f for f in glob.glob(os.path.join(d, "*.md"))
                     if "生词" in os.path.basename(f)
                     or os.path.splitext(os.path.basename(f))[0] == stem]
            if len(cands) == 1:
                return cands[0], True
    return path, False


def autodiscover():
    """桌面上的 生词.md 只要出现（或重新出现）就自动纳入词源"""
    sources = load_json(SRC_F, None)
    if not sources:
        sources = []
        # 先扫项目目录（自带示例词表在这），再扫桌面（多数人把生词.md 放那）
        for d in (BASE, os.path.dirname(DEFAULT_MD)):
            for path in sorted(glob.glob(os.path.join(d, "生词*.md"))):
                if all(s["path"] != path for s in sources):
                    sources.append({"path": path, "name": os.path.basename(path)})
        save_json(SRC_F, sources)
        return sources

    # 文件被移动/改名时自动修正，不然词表会读成空
    changed = False
    for s in sources:
        real, moved = resolve_source(s.get("path", ""), s.get("name", ""))
        if real and real != s.get("path"):
            print("[info] 词表位置变了：%s -> %s" % (s.get("path"), real))
            s["path"] = real
            s["name"] = os.path.basename(real)
            changed = True
    if os.path.exists(DEFAULT_MD) and all(s["path"] != DEFAULT_MD for s in sources):
        sources.append({"path": DEFAULT_MD, "name": os.path.basename(DEFAULT_MD)})
        changed = True
    if changed:
        save_json(SRC_F, sources)
        _cache.clear()
    return sources


def all_words(force=False):
    if force:
        _cache.clear()
    sources = autodiscover()

    vocab = load_json(DICT_F, {})
    merged, counts = {}, []
    for s in sources:
        ws = read_source(s["path"], s["name"])
        counts.append({"name": s["name"], "path": s["path"], "count": len(ws),
                       "exists": os.path.exists(s["path"])})
        for it in ws:
            w = it["w"]
            if w in merged:
                old = merged[w]
                if not old["meaning"] and it["meaning"]:
                    old["meaning"] = it["meaning"]
                if not old["tip"] and it["tip"]:
                    old["tip"] = it["tip"]
                if not old.get("ctx") and it.get("ctx"):
                    old["ctx"] = it["ctx"]
                continue
            merged[w] = dict(it)

    # 本地释义库补齐 / 覆盖空释义
    for w, it in merged.items():
        d = vocab.get(w)
        if d:
            if not it["meaning"]:
                it["meaning"] = d.get("m", "")
            if not it["tip"]:
                it["tip"] = d.get("tip", "")
            if not it.get("ctx"):
                it["ctx"] = d.get("ctx", "")          # 划词带的原句存在释义库里
            it["ph"] = d.get("ph", "")
    return merged, counts, sources


def build_state(force=False):
    merged, counts, sources = all_words(force)
    prog = load_json(PROG_F, {"words": {}})
    vocab = load_json(DICT_F, {})
    pw = prog.setdefault("words", {})

    # 兜底：词表文件丢了/被移走了，学过的词（尤其收藏）也不能消失，
    # 用释义库补上意思，标成「词表外」，这样收藏本永远是完整的
    orphan = []
    for w, st in pw.items():
        if not st or w in merged:
            continue
        d = vocab.get(w) or {}
        merged[w] = {"w": w, "meaning": d.get("m", ""), "tip": d.get("tip", ""),
                     "ctx": d.get("ctx", ""),
                     "ph": d.get("ph", ""), "section": d.get("section", "词表外"),
                     "src": "学习记录"}
        orphan.append(w)

    words = []
    for w in sorted(merged):
        it = merged[w]
        st = pw.get(w)
        words.append({
            "w": w,
            "m": it["meaning"],
            "ph": it.get("ph", ""),
            "tip": it["tip"],
            "ctx": it.get("ctx", ""),
            "sec": it["section"],
            "src": it["src"],
            "st": st,
        })
    missing = [w["w"] for w in words if not w["m"]]
    fav = sum(1 for w in words if w["st"] and w["st"].get("fav") and not w["st"].get("mastered"))
    new = sum(1 for w in words if not w["st"])
    done_today = len(prog.get("daily", {}).get(today(), {}).get("done", []))
    issues = [c for c in counts if not c["exists"]]
    # 加词的默认落点：优先第一个真实存在的词表，其次桌面 生词.md
    target = next((c["path"] for c in counts if c["exists"]), DEFAULT_MD)
    return {
        "words": words,
        "sources": counts,
        "missing": missing,
        "sourceIssues": issues,
        "orphanCount": len(orphan),
        "stats": {"total": len(words), "new": new, "fav": fav,
                  "learned": len(words) - new, "today": today(),
                  "doneToday": done_today},
        "defaultTarget": target,
    }


# ---------- 学习记录 ----------

def migrate_fav_at():
    """以前只记了日期没有收藏时刻。用最后一次练习日期 + 记录写入顺序回填一个近似值，
    同一天里的先后靠 ord 撑着（progress.json 的键顺序就是首次写入顺序）。"""
    prog = load_json(PROG_F, {"words": {}})
    pw = prog.get("words") or {}
    changed = False
    for i, (w, st) in enumerate(pw.items()):
        if not isinstance(st, dict):
            continue
        if st.get("fav") and not st.get("favAt"):
            day = st.get("last") or st.get("first") or today()
            st["favAt"] = "%sT12:00:00" % day
            st["ord"] = i
            changed = True
        elif not st.get("fav"):
            if st.pop("favAt", None) is not None:
                changed = True
    if changed:
        save_json(PROG_F, prog)
    return changed


def mark_word(word, right, fav=None, mastered=None, requeue=False):
    prog = load_json(PROG_F, {"words": {}})
    pw = prog.setdefault("words", {})
    st = pw.get(word) or {"seen": 0, "right": 0, "wrong": 0, "box": 0,
                          "fav": False, "mastered": False, "due": today()}
    st["seen"] += 1
    st["last"] = today()
    st.setdefault("first", today())
    if right:
        st["right"] += 1
        st["box"] = min(MAX_BOX, st.get("box", 0) + 1)
        st["due"] = (date.today() + timedelta(days=INTERVALS[st["box"]])).isoformat()
        if st["box"] >= MAX_BOX and st.get("fav"):
            st["mastered"] = True
            st["fav"] = False
            st.pop("favAt", None)
    else:
        st["wrong"] += 1
        st["box"] = 0
        st["due"] = today() if requeue else (date.today() + timedelta(days=1)).isoformat()
        st["mastered"] = False
    if fav is True:
        st["fav"] = True
        st["mastered"] = False
        st["favAt"] = now_ts()          # 收藏时间，收藏本按它排
    elif fav is False:
        st["fav"] = False
        st.pop("favAt", None)
    if mastered is not None:
        st["mastered"] = mastered
        if mastered:
            st["fav"] = False
            st.pop("favAt", None)
    pw[word] = st
    # 今日已过（服务端记，换浏览器 / 重开页面都还在）
    daily = prog.setdefault("daily", {})
    rec = daily.setdefault(today(), {"done": []})
    if word not in rec["done"]:
        rec["done"].append(word)
    save_json(PROG_F, prog)
    return st


# ---------- 联网补释义（有道） ----------

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def _get(url, timeout=8):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


def clean_meaning(s):
    s = re.sub(r"\s+", " ", s or "").strip()
    s = s.replace("；", ";")
    parts = [p.strip() for p in s.split(";") if p.strip()]
    s = "；".join(parts[:2])
    return s[:60]


# ---------- 词形还原 ----------
# 阅读里遇到的大多是变形（staples / running / carried），照原样查经常查不到。
# 先查原样，查不到再按规则猜原形试一遍。猜错也没损失，只是多一次请求。

IRREGULAR = {
    "am": "be", "is": "be", "are": "be", "was": "be", "were": "be", "been": "be",
    "has": "have", "had": "have", "having": "have", "does": "do", "did": "do",
    "done": "do", "doing": "do", "went": "go", "gone": "go", "goes": "go",
    "said": "say", "says": "say", "got": "get", "gotten": "get", "made": "make",
    "took": "take", "taken": "take", "came": "come", "saw": "see", "seen": "see",
    "knew": "know", "known": "know", "thought": "think", "felt": "feel",
    "kept": "keep", "left": "leave", "meant": "mean", "paid": "pay", "laid": "lay",
    "led": "lead", "held": "hold", "stood": "stand", "understood": "understand",
    "began": "begin", "begun": "begin", "brought": "bring", "built": "build",
    "bought": "buy", "caught": "catch", "taught": "teach", "chose": "choose",
    "chosen": "choose", "dealt": "deal", "drew": "draw", "drawn": "draw",
    "drove": "drive", "driven": "drive", "ate": "eat", "eaten": "eat",
    "fell": "fall", "fallen": "fall", "fed": "feed", "flew": "fly", "flown": "fly",
    "forgot": "forget", "forgotten": "forget", "froze": "freeze", "frozen": "freeze",
    "gave": "give", "given": "give", "grew": "grow", "grown": "grow",
    "heard": "hear", "hid": "hide", "hidden": "hide", "lost": "lose", "met": "meet",
    "rode": "ride", "ridden": "ride", "rang": "ring", "rung": "ring",
    "rose": "rise", "risen": "rise", "sang": "sing", "sung": "sing",
    "sank": "sink", "sunk": "sink", "sat": "sit", "slept": "sleep",
    "spoke": "speak", "spoken": "speak", "spent": "spend", "stuck": "stick",
    "struck": "strike", "swam": "swim", "swum": "swim", "told": "tell",
    "threw": "throw", "thrown": "throw", "woke": "wake", "woken": "wake",
    "wore": "wear", "worn": "wear", "wrote": "write", "written": "write",
    "won": "win", "wound": "wind", "shook": "shake", "shaken": "shake",
    "broke": "break", "broken": "break", "chose": "choose", "found": "find",
    "sent": "send", "spent": "spend", "sold": "sell", "told": "tell",
    "children": "child", "feet": "foot", "teeth": "tooth", "mice": "mouse",
    "men": "man", "women": "woman", "geese": "goose", "lives": "life",
    "wives": "wife", "knives": "knife", "wolves": "wolf", "leaves": "leaf",
    "selves": "self", "halves": "half", "shelves": "shelf", "thieves": "thief",
    "better": "good", "best": "good", "worse": "bad", "worst": "bad",
    "further": "far", "furthest": "far", "elder": "old", "data": "datum",
}

VOWELS = set("aeiou")


def lemma_candidates(w):
    """猜几个可能的原形，把握高的排前面。只用来补释义，不改收录的词形。"""
    out = []
    lw = (w or "").lower()

    def add(x):
        if x and x != lw and len(x) >= 2 and x not in out:
            out.append(x)

    if lw in IRREGULAR:
        add(IRREGULAR[lw])

    # 变形里最多的是复数，先试去 s，再去 es。
    # staples -> staple（对）、boxes -> boxe（错，下一个候选 box 才命中）
    if lw.endswith("ies") and len(lw) > 4:            # studies -> study
        add(lw[:-3] + "y")
    if lw.endswith("ves") and len(lw) > 4:            # leaves -> leaf / life
        add(lw[:-3] + "f")
        add(lw[:-3] + "fe")
    if lw.endswith("s") and not lw.endswith(("ss", "us", "is")) and len(lw) > 3:
        add(lw[:-1])
    if lw.endswith("es") and len(lw) > 4:
        add(lw[:-2])

    for suf in ("ing", "ed", "er", "est"):
        if not lw.endswith(suf) or len(lw) <= len(suf) + 2:
            continue
        stem = lw[: -len(suf)]
        add(stem)                                     # walking -> walk
        add(stem + "e")                               # hoping -> hope
        if len(stem) >= 2 and stem[-1] == stem[-2] and stem[-1] not in VOWELS:
            add(stem[:-1])                            # running -> run
        if suf == "ed" and stem.endswith("i"):
            add(stem[:-1] + "y")                      # carried -> carry

    return out


# 有道对变形词会给「n. 主要产物（staple 的复数）」这种带括号的释义，
# 不如还原成原形拿到的干净，见到这种标记就换个查法
INFLECT_MARK = re.compile(
    r"[（(][^）)]*的(复数|单数|过去式|过去分词|现在分词|第三人称|比较级|最高级)[）)]")


def lookup(word):
    """返回 (中文意思, 音标, 来源, 命中的原形)。原样查不到、或查到的是变形释义时，
    改用词形还原的结果。命中还原形时 tip 会带上「原形 xxx」。"""
    m, ph, src = _lookup_raw(word)
    if m and not INFLECT_MARK.search(m):
        return m, ph, src, ""
    for c in lemma_candidates(word):
        m2, ph2, src2 = _lookup_raw(c)
        if m2:
            return m2, ph2, src2, c
    return m, ph, src, ""        # 还原也没查到，退回原样（可能是空）


def _lookup_raw(word):
    """返回 (中文意思, 音标, 来源)。有道两个接口依次尝试。"""
    q = urllib.parse.quote(word)
    # 1) suggest：释义最干净
    try:
        j = json.loads(_get("https://dict.youdao.com/suggest?q=%s&doctype=json&num=1&le=en" % q))
        for e in (j.get("data") or {}).get("entries") or []:
            if (e.get("entry") or "").lower() == word.lower() and e.get("explain"):
                return clean_meaning(e["explain"]), "", "youdao"
        ents = (j.get("data") or {}).get("entries") or []
        if ents and ents[0].get("explain"):
            return clean_meaning(ents[0]["explain"]), "", "youdao"
    except Exception:
        pass
    # 2) jsonapi：ec 里能拿到音标
    try:
        j = json.loads(_get("https://dict.youdao.com/jsonapi?q=%s" % q))
        ec = j.get("ec") or {}
        ws = ec.get("word") or []
        if ws:
            head = ws[0]
            phone = head.get("usphone") or head.get("ukphone") or ""
            out = []
            for tr in (head.get("trs") or [])[:2]:
                for l in tr.get("tr") or []:
                    for i in ((l.get("l") or {}).get("i") or []):
                        if i:
                            out.append(re.sub(r"<[^>]+>", "", str(i)).strip())
            if out:
                return clean_meaning("；".join(out[:2])), phone, "youdao"
            return "", phone, "youdao"
        wt = j.get("web_trans") or {}
        tr = wt.get("web-translation") or []
        if tr:
            return clean_meaning("；".join([t.get("key", "") for t in tr[:2]])), "", "youdao"
    except Exception:
        pass
    return "", "", ""


def fill_missing(words):
    vocab = load_json(DICT_F, {})
    done, fail = [], []
    todo = [w for w in words if w and not vocab.get(w, {}).get("m")]
    if not todo:
        return {"ok": 0, "fail": 0, "updated": []}

    def one(w):
        """返回 (词, 释义, 音标, 来源, 命中的原形)"""
        try:
            m, ph, src, lemma = lookup(w)
        except Exception:
            m, ph, src, lemma = "", "", "", ""
        return w, m, ph, src, lemma

    with ThreadPoolExecutor(max_workers=12) as ex:
        for w, m, ph, src, lemma in ex.map(one, todo):
            if m:
                d = vocab.get(w) or {}
                d.update({"m": m, "ph": ph, "src": src})
                d.setdefault("tip", "")
                if lemma:
                    d["tip"] = "原形 %s" % lemma    # 让人知道这个词是变形
                    d["lemma"] = lemma
                vocab[w] = d
                done.append({"w": w, "m": m, "lemma": lemma})
            else:
                fail.append(w)
    save_json(DICT_F, vocab)
    return {"ok": len(done), "fail": len(fail), "updated": done}


# ---------- 导出 ----------

def export_md():
    state = build_state()
    prog = load_json(PROG_F, {"words": {}})
    lines = ["# 生词整理（导出 %s）" % today(), "",
             "共 %d 词。★ = 收藏中，√ = 已掌握。" % state["stats"]["total"], ""]
    by = {}
    for w in state["words"]:
        by.setdefault(w["sec"], []).append(w)
    for sec, ws in by.items():
        lines.append("## %s" % sec)
        lines.append("")
        # 第 5 列是划词时带的原句，parse_md 只读前 3 列，多出来这一列不影响回读
        has_ctx = any(w.get("ctx") for w in ws)
        if has_ctx:
            lines.append("| 单词 | 中文意思 | 提示 | 状态 | 原句 |")
            lines.append("| --- | --- | --- | --- | --- |")
        else:
            lines.append("| 单词 | 中文意思 | 提示 | 状态 |")
            lines.append("| --- | --- | --- | --- |")
        for w in ws:
            st = w["st"] or {}
            tag = "√" if st.get("mastered") else ("★" if st.get("fav") else "")
            row = "| **%s** | %s | %s | %s |" % (w["w"], w["m"], w["tip"], tag)
            if has_ctx:
                ctx = (w.get("ctx") or "").replace("|", "/").replace("\n", " ")
                row += " %s |" % ctx[:120]
            lines.append(row)
        lines.append("")
    return "\n".join(lines)


# ---------- HTTP ----------

class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        # 划词扩展的源是 chrome-extension://...，跨域过来必须放开。
        # 服务只绑 127.0.0.1，外人连不上，这里放开是可以接受的
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def static(self, name, ctype):
        try:
            with open(os.path.join(WEB, name), "rb") as f:
                self.send(200, f.read(), ctype)
        except Exception:
            self.send(404, "not found", "text/plain; charset=utf-8")

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    def do_OPTIONS(self):
        # 预检请求，浏览器发 POST application/json 前会先来一次
        self.send(204, b"")

    def do_GET(self):
        p = urllib.parse.urlparse(self.path).path
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if p in ("/", "/index.html"):
            return self.static("index.html", "text/html; charset=utf-8")
        if p == "/app.js":
            return self.static("app.js", "application/javascript; charset=utf-8")
        if p == "/style.css":
            return self.static("style.css", "text/css; charset=utf-8")
        if p == "/api/state":
            return self.send(200, json.dumps(build_state(force=bool(q.get("reload"))),
                                             ensure_ascii=False))
        if p == "/api/export":
            if q.get("fmt", ["md"])[0] == "json":
                return self.send(200, json.dumps(build_state(), ensure_ascii=False))
            return self.send(200, export_md(), "text/markdown; charset=utf-8")
        self.send(404, json.dumps({"err": "not found"}))

    def do_POST(self):
        p = urllib.parse.urlparse(self.path).path
        b = self.body()
        if p == "/api/mark":
            st = mark_word(b.get("word", ""), bool(b.get("right")),
                           b.get("fav"), b.get("mastered"), bool(b.get("requeue")))
            return self.send(200, json.dumps(st, ensure_ascii=False))
        if p == "/api/append":                         # 批量加词
            target = b.get("target") or DEFAULT_MD
            section = (b.get("section") or "").strip()
            text = b.get("text") or ""
            exist = ""
            if os.path.exists(target):
                with open(target, "r", encoding="utf-8", errors="ignore") as f:
                    exist = f.read()
            if section and section not in exist:
                text = section + "\n" + text
            with open(target, "a", encoding="utf-8") as f:
                if exist and not exist.endswith("\n"):
                    f.write("\n")
                f.write(text.rstrip() + "\n")
            sources = autodiscover()
            if all(s["path"] != target for s in sources):
                sources.append({"path": target, "name": os.path.basename(target)})
                save_json(SRC_F, sources)
            _cache.clear()
            added = [i["w"] for i in parse_md(text, "")]

            # 划词扩展带过来的原句，存进释义库（不写进 md，免得和状态列打架）
            ctxs = b.get("ctxs") or {}
            ctx_n = 0
            if ctxs:
                vocab = load_json(DICT_F, {})
                for w, c in ctxs.items():
                    w = norm(w)
                    c = (c or "").strip()
                    if not w or not c:
                        continue
                    d = vocab.get(w) or {}
                    if d.get("ctx") and d["ctx"] != c:
                        d["ctx"] = (d["ctx"] + " // " + c)[:400]
                    else:
                        d["ctx"] = c[:400]
                    vocab[w] = d
                    ctx_n += 1
                save_json(DICT_F, vocab)

            # 扩展收录时通常顺手就要释义，省得它再发一次请求
            filled = None
            if b.get("fill") and added:
                filled = fill_missing(added)

            return self.send(200, json.dumps(
                {"added": added, "count": len(added), "path": target,
                 "ctx": ctx_n, "filled": (filled or {}).get("ok", 0)}, ensure_ascii=False))
        if p == "/api/fav":                            # 只改收藏状态，不计入练习次数
            prog = load_json(PROG_F, {"words": {}})
            pw = prog.setdefault("words", {})
            w = norm(b.get("word", ""))
            st = pw.get(w) or {"seen": 0, "right": 0, "wrong": 0, "box": 0,
                               "fav": False, "mastered": False, "due": today()}
            fav = bool(b.get("fav"))
            st["fav"] = fav
            st["mastered"] = bool(b.get("mastered")) if "mastered" in b else st.get("mastered", False)
            if fav:
                st["mastered"] = False
                st["favAt"] = now_ts()
            else:
                st.pop("favAt", None)
            st.setdefault("first", today())
            st["last"] = today()
            pw[w] = st
            save_json(PROG_F, prog)
            return self.send(200, json.dumps(st, ensure_ascii=False))
        if p == "/api/dict":
            vocab = load_json(DICT_F, {})
            ups = b.get("updates") or [b]
            for u in ups:
                w = norm(u.get("word", ""))
                if not w:
                    continue
                d = vocab.get(w) or {}
                if "meaning" in u:
                    d["m"] = u["meaning"]
                if "tip" in u:
                    d["tip"] = u["tip"]
                if "ctx" in u:
                    d["ctx"] = u["ctx"]
                d["src"] = "manual"
                vocab[w] = d
            save_json(DICT_F, vocab)
            return self.send(200, json.dumps({"ok": len(ups)}, ensure_ascii=False))
        if p == "/api/fill":
            ws = b.get("words") or build_state().get("missing") or []
            ws = ws[: int(b.get("limit", 300))]
            return self.send(200, json.dumps(fill_missing(ws), ensure_ascii=False))
        if p == "/api/source/add":
            sources = load_json(SRC_F, [])
            if b.get("content"):                       # 上传的文件内容
                os.makedirs(UPLOADS, exist_ok=True)
                name = b.get("name") or ("上传_%s.md" % time.strftime("%Y%m%d%H%M%S"))
                path = os.path.join(UPLOADS, name)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(b["content"])
            else:
                path = b.get("path", "")
                name = os.path.basename(path)
            if path and all(s["path"] != path for s in sources):
                sources.append({"path": path, "name": name})
                save_json(SRC_F, sources)
            _cache.clear()
            return self.send(200, json.dumps({"sources": sources}, ensure_ascii=False))
        if p == "/api/source/remove":
            path = b.get("path", "")
            sources = [s for s in load_json(SRC_F, []) if s["path"] != path]
            save_json(SRC_F, sources)
            return self.send(200, json.dumps({"sources": sources}, ensure_ascii=False))
        if p == "/api/reset":
            scope = b.get("scope", "")
            backup_progress("beforereset")          # 手滑清空也能捞回来
            prog = load_json(PROG_F, {"words": {}})
            if scope == "all":
                prog["words"] = {}
                prog["daily"] = {}
            elif scope == "fav":
                for w, st in prog.get("words", {}).items():
                    st["fav"] = False
            save_json(PROG_F, prog)
            return self.send(200, json.dumps({"ok": True}, ensure_ascii=False))
        self.send(404, json.dumps({"err": "not found"}))


def pick_port(start=8756, host="127.0.0.1"):
    import socket
    for p in range(start, start + 20):
        with socket.socket() as s:
            try:
                s.bind((host, p))
                return p
            except OSError:
                continue
    return start


def local_ip():
    """拿本机的局域网地址，给 0.0.0.0 模式显示用"""
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def parse_args(argv):
    """只认三个参数，其余忽略：
    --no-browser  启动后不自动开浏览器
    --port=8760   指定端口（默认从 8756 起自动找空位）
    --host=0.0.0.0  允许局域网/手机访问（默认 127.0.0.1，只本机）
    """
    a = {"host": "127.0.0.1", "port": 0, "browser": True}
    for s in argv[1:]:
        if s == "--no-browser":
            a["browser"] = False
        elif s.startswith("--port="):
            try:
                a["port"] = int(s.split("=", 1)[1])
            except ValueError:
                pass
        elif s.startswith("--host="):
            a["host"] = s.split("=", 1)[1] or "127.0.0.1"
    return a


def main():
    args = parse_args(sys.argv)
    host = args["host"]
    os.makedirs(DATA, exist_ok=True)
    os.makedirs(WEB, exist_ok=True)
    os.makedirs(UPLOADS, exist_ok=True)
    if not os.path.exists(DICT_F):
        save_json(DICT_F, {})
    if not os.path.exists(PROG_F):
        save_json(PROG_F, {"words": {}})
    n = len(load_json(PROG_F, {}).get("words", {}))
    if n:
        backup_progress("start")
    migrate_fav_at()
    port = args["port"] or pick_port(host=host)
    url = "http://%s:%d/" % (local_ip() if host in ("0.0.0.0", "") else host, port)
    srv = ThreadingHTTPServer((host, port), H)
    try:
        for s in autodiscover():               # 顺手把走丢的词表找回来
            if not os.path.exists(s["path"]):
                print(" [注意] 词表文件找不到：%s" % s["path"])
    except Exception:
        pass
    print("=" * 46)
    print(" 刷词已启动： %s" % url)
    print(" 学习记录：%d 个词（已备份到 data/backup）" % n)
    print(" 关掉这个黑窗口就停止服务")
    print("=" * 46)
    if host not in ("127.0.0.1", "localhost", "::1"):
        print(" [注意] 已放开到 %s：同一网络的设备都能打开，服务没有做登录鉴权，" % host)
        print("        只在自己家里/可信网络里这么用。")
    if args["browser"]:
        threading = __import__("threading")
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
